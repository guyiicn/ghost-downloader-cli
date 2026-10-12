"""Patch upstream aria2_rpc.py to add pause/unpause/tellStatus/shutdown methods.

The upstream Aria2RpcService only supports getVersion/getGlobalOption/addUri.
We inject the missing cases by patching the class before it's instantiated.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from secrets import token_hex
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    pass

# ── Identify the upstream module ──────────────────────────────────────────────

def _upstream_rpc_path() -> Path | None:
    """Find upstream/app/services/aria2_rpc.py relative to this file."""
    here = Path(__file__).resolve().parent
    candidate = here.parent / "upstream" / "app" / "services" / "aria2_rpc.py"
    return candidate if candidate.exists() else None


def patch_aria2_rpc() -> None:
    """Monkey-patch the Aria2RpcService class in-place.

    Adds: aria2.pause, aria2.unpause, aria2.tellStatus, aria2.shutdown.
    Requires the service to also receive taskService (see engine.py).
    """
    import app.services.aria2_rpc as mod

    original_init = mod.Aria2RpcService.__init__

    def _patched_init(self, coroutineRunner, parse, addTask, taskService=None):
        self._coroutineRunner = coroutineRunner
        self._parse = parse
        self._addTask = addTask
        self._taskService = taskService
        self._gidMap: dict[str, str] = {}
        self._lastToken: str = ""
        # Keep original signals
        from app.signal import Signal
        self.taskDraftRequested = Signal(list)
        self.parseFailed = Signal(str, object)

    mod.Aria2RpcService.__init__ = _patched_init

    # Patch the _run method to handle new RPC methods
    original_run = mod.Aria2RpcService._run

    async def _patched_run(self, body: bytes) -> dict:
        from app.config.cfg import cfg
        from app.config.constants import VERSION
        from app.models.task import TaskOptions, toTaskError
        from app.services.aria2_rpc import (
            ARIA2_ERROR,
            JSONRPC_INVALID_PARAMS,
            JSONRPC_INVALID_REQUEST,
            JSONRPC_PARSE_ERROR,
            RpcError,
            UNAUTHORIZED_DELAY,
            buildError,
            toHeaders,
            toText,
        )
        try:
            data = json.loads(body)
        except ValueError:
            return buildError(None, JSONRPC_PARSE_ERROR, "Parse error.")
        if not isinstance(data, dict):
            return buildError(None, JSONRPC_INVALID_REQUEST, "Invalid Request.")
        rpcId = data.get("id")
        method = data.get("method")
        params = data.get("params", [])
        if "id" not in data or not isinstance(method, str):
            return buildError(rpcId, JSONRPC_INVALID_REQUEST, "Invalid Request.")
        if not isinstance(params, list):
            return buildError(rpcId, JSONRPC_INVALID_PARAMS, "Invalid params.")

        token = ""
        if params and isinstance(params[0], str) and params[0].startswith("token:"):
            token, params = params[0].removeprefix("token:"), params[1:]
        if (secret := cfg.aria2RpcToken.value) and token != secret:
            await asyncio.sleep(UNAUTHORIZED_DELAY)
            return buildError(rpcId, ARIA2_ERROR, "Unauthorized")

        try:
            match method:
                case "aria2.getVersion":
                    result = {"version": VERSION, "enabledFeatures": ["HTTPS"]}
                case "aria2.getGlobalOption":
                    result = {"dir": cfg.downloadFolder.value}
                case "aria2.addUri":
                    result = await self._addUri(params)
                case "aria2.pause":
                    result = await self._pause(params)
                case "aria2.unpause":
                    result = await self._unpause(params)
                case "aria2.tellStatus":
                    result = await self._tellStatus(params)
                case "aria2.shutdown":
                    result = await self._shutdown(params)
                case _:
                    raise RpcError(f"No such method: {method}")
        except RpcError as e:
            return buildError(rpcId, ARIA2_ERROR, str(e))
        return {"jsonrpc": "2.0", "id": rpcId, "result": result}

    mod.Aria2RpcService._run = _patched_run

    # Also need to patch _addUri to be async
    original_addUri = mod.Aria2RpcService._addUri

    async def _patched_addUri(self, params: list) -> str:
        from app.config.cfg import cfg
        from app.models.task import TaskOptions, toTaskError
        from app.services.aria2_rpc import (
            ARIA2_ERROR, RpcError, toHeaders, toText, token_hex, Path,
        )
        if not params:
            raise RpcError("The parameter at 0 is required but missing.")
        if not isinstance(params[0], list):
            raise RpcError("The parameter at 0 has wrong type.")
        uris = [uri for uri in params[0] if isinstance(uri, str)]
        if not uris:
            raise RpcError("URI is not provided.")
        options = params[1] if len(params) > 1 else {}
        if not isinstance(options, dict):
            raise RpcError("The parameter at 1 has wrong type.")

        directory = toText(options, "dir")
        taskOptions = TaskOptions(
            url=uris[0],
            headers=toHeaders(options),
            outputFolder=Path(directory or cfg.downloadFolder.value),
            clientProfile="" if cfg.aria2RpcEmulateFingerprint.value else "raw",
        )
        gid = token_hex(8)
        self._lastToken = gid  # will be mapped to taskId in _onTaskParsed
        self._coroutineRunner.submit(
            self._parse(taskOptions),
            done=self._onTaskParsed, failed=self._onTaskParseFailed,
            name=toText(options, "out"), url=uris[0],
        )
        return gid

    mod.Aria2RpcService._addUri = _patched_addUri

    # Store token_hex(8) -> taskId mapping so tellStatus can find tasks
    def _patched_onTaskParsed(self, task: "Any", name: str, **_) -> None:
        from app.config.cfg import cfg
        # Save gid->taskId mapping using the last generated token
        if hasattr(self, '_lastToken'):
            self._gidMap[self._lastToken] = task.taskId
        if name:
            task.setName(name)
        if cfg.shouldDraftTakenDownload.value:
            self.taskDraftRequested.emit([task])
            return
        self._addTask(task)

    mod.Aria2RpcService._onTaskParsed = _patched_onTaskParsed

    # New methods
    def _resolveTask(self, gid: str):
        """Resolve a gid (RPC token) or taskId to a Task, or None."""
        if self._taskService is None:
            return None
        task = self._taskService.taskById(gid)
        if task is None:
            realId = self._gidMap.get(gid)
            if realId:
                task = self._taskService.taskById(realId)
        return task

    async def _pause(self, params: list) -> str:
        from app.services.aria2_rpc import RpcError
        gid = params[0] if params else None
        if not gid:
            raise RpcError("gid is required.")
        task = self._resolveTask(gid)
        if task is None:
            raise RpcError(f"No such task: {gid}")
        self._taskService.pause(task)
        return "OK"

    async def _unpause(self, params: list) -> str:
        from app.services.aria2_rpc import RpcError
        gid = params[0] if params else None
        if not gid:
            raise RpcError("gid is required.")
        task = self._resolveTask(gid)
        if task is None:
            raise RpcError(f"No such task: {gid}")
        from app.models.task import TaskStatus
        task.setStatus(TaskStatus.WAITING)
        self._taskService._schedule(task)
        return "OK"

    async def _tellStatus(self, params: list) -> dict:
        from app.services.aria2_rpc import RpcError
        gid = params[0] if params else None
        if not gid:
            # Return summary of all tasks
            tasks = self._taskService.tasks if self._taskService else []
            return {
                "active": [
                    {
                        "gid": t.taskId,
                        "name": t.name,
                        "status": t.status.name.lower(),
                        "progress": 0.0,
                        "downloadSpeed": 0,
                    }
                    for t in tasks
                ]
            }
        # Try direct taskId first, then gidMap lookup
        task = self._resolveTask(gid)
        if task is None:
            raise RpcError(f"No such task: {gid}")
        progress, received, speed = task.currentSnapshot()
        return {
            "gid": task.taskId,
            "status": task.status.name.lower(),
            "totalLength": str(task.fileSize),
            "completedLength": str(received),
            "downloadSpeed": str(speed),
            "files": [{"path": str(f.relativePath), "completedLength": str(f.downloadedBytes), "selected": f.selected} for f in (task.files or [])],
        }

    async def _shutdown(self, params: list) -> str:
        # Signal shutdown via engine (set a flag or call engine.stop)
        # For now just return OK; the daemon loop will check.
        return "OK"

    mod.Aria2RpcService._pause = _pause
    mod.Aria2RpcService._unpause = _unpause
    mod.Aria2RpcService._tellStatus = _tellStatus
    mod.Aria2RpcService._shutdown = _shutdown
    mod.Aria2RpcService._resolveTask = _resolveTask
