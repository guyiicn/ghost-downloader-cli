"""gd-cli — headless command line for Ghost-Downloader-3.

Subcommands:
  download  One-shot download (blocks until finished).
  daemon    Start the background engine with aria2-compatible RPC.
  rpc       Talk to a running daemon (add/pause/resume/list/shutdown).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

from cli.stubs import _install as _ensureStubs


def _bootstrapUpstream() -> None:
    """Make upstream/ importable whether run from source tree or site-packages."""
    import sys
    from pathlib import Path as _P
    here = _P(__file__).resolve().parent
    candidates = [here.parent / "upstream", here.parent.parent / "upstream"]
    for cand in candidates:
        if cand.is_dir() and str(cand) not in sys.path:
            sys.path.insert(0, str(cand))
            feats = cand / "features"
            if feats.is_dir():
                sys.path.insert(0, str(feats))
            break


_ensureStubs()

DEFAULT_RPC_PORT = 16800
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "ghost-downloader-cli"

_bootstrapUpstream()  # noqa: E402  (must precede app.* imports)


# ── RPC client ────────────────────────────────────────────────────────────────

def rpcCall(port: int, method: str, params: list, token: str = "") -> Any:
    if token:
        params = [f"token:{token}", *params]
    payload = json.dumps({"jsonrpc": "2.0", "id": "gd-cli", "method": method, "params": params}).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/jsonrpc", data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as resp:
        body = json.loads(resp.read())
    if "error" in body:
        raise RuntimeError(f"RPC error: {body['error']}")
    return body["result"]


# ── download ──────────────────────────────────────────────────────────────────

def cmdDownload(args) -> int:
    from app.config.cfg import cfg
    from app.models.task import TaskStatus
    from cli.engine import createEngine

    engine, runner = createEngine(configFolder=args.config, downloadFolder=args.output)

    state: dict = {}

    async def run() -> None:
        from app.models.task import TaskOptions
        options = TaskOptions(
            url=args.url,
            outputFolder=Path(args.output).resolve() if args.output else Path(cfg.downloadFolder.value),
            clientProfile="",
        )
        task = await engine.featureService.parse(options)
        if args.name:
            task.setName(args.name)
        from app.services.task_service import NameConflictChoice
        engine.taskService.add(
            task,
            choice=NameConflictChoice.OVERWRITE if args.overwrite else NameConflictChoice.KEEP_BOTH,
        )
        state["task"] = task

    runner.submit(run(), failed=lambda e: state.setdefault("error", e))

    def progressLine() -> str:
        task = state.get("task")
        if task is None:
            return "parsing…"
        progress, received, _speed = task.currentSnapshot()
        return f"{task.status.name.lower()} {progress:6.2f}% {received}/{max(task.fileSize, 0)}B"

    deadline = time.monotonic() + args.timeout * 60 if args.timeout else None
    exitCode = 0
    try:
        while True:
            time.sleep(0.5)
            if "error" in state:
                print(f"\n❌ {state['error']!r}", file=sys.stderr)
                exitCode = 1
                break
            task = state.get("task")
            if task is not None:
                if args.progress:
                    print("\r" + progressLine(), end="", flush=True)
                if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.PAUSED}:
                    if args.progress:
                        print()
                    break
            if deadline and time.monotonic() > deadline:
                print("\n⏱️ timeout", file=sys.stderr)
                exitCode = 2
                break
    except KeyboardInterrupt:
        # engine.stop() persists state; next daemon/start resumes WAITING tasks.
        print("\n↩︎ interrupted; progress saved", file=sys.stderr)
        exitCode = 130
    finally:
        engine.stop()

    task = state.get("task")
    if task is not None:
        label = {TaskStatus.COMPLETED: "✅", TaskStatus.FAILED: "❌"}.get(task.status, "⚠️")
        print(f"{label} {task.status.name.lower()}: {task.name} → {task.outputPath}")
        exitCode = exitCode or (0 if task.status == TaskStatus.COMPLETED else 1)
    return exitCode


# ── daemon ────────────────────────────────────────────────────────────────────

def cmdDaemon(args) -> int:
    from app.config.cfg import cfg
    from cli.engine import createEngine, waitForever

    engine, _runner = createEngine(configFolder=args.config, downloadFolder=args.output)
    print(f"gd-cli daemon: RPC on 127.0.0.1:{cfg.aria2RpcPort.value}, "
          f"downloads → {cfg.downloadFolder.value}", file=sys.stderr)
    try:
        waitForever()
    finally:
        engine.stop()
    return 0


# ── rpc ───────────────────────────────────────────────────────────────────────

def cmdRpc(args) -> int:
    port, token = args.rpc_port, args.rpc_token
    if args.rpc_command == "add":
        options: dict = {}
        if args.output:
            options["dir"] = str(Path(args.output).resolve())
        if args.name:
            options["out"] = args.name
        print(rpcCall(port, "aria2.addUri", [[args.url], options], token))
    elif args.rpc_command == "list":
        result = rpcCall(port, "gd.tellActive", [], token)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.rpc_command == "pause":
        print(rpcCall(port, "aria2.pause", [args.target], token))
    elif args.rpc_command == "resume":
        print(rpcCall(port, "aria2.unpause", [args.target], token))
    elif args.rpc_command == "status":
        result = rpcCall(port, "aria2.tellStatus", [args.target], token)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.rpc_command == "shutdown":
        print(rpcCall(port, "aria2.shutdown", [], token))
    return 0


# ── parser ────────────────────────────────────────────────────────────────────

def buildParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gd-cli", description="Ghost-Downloader headless CLI (unofficial)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("download", help="one-shot download, blocks until done")
    p.add_argument("url")
    p.add_argument("-o", "--output", help="output folder")
    p.add_argument("-N", "--name", help="save as filename")
    p.add_argument("--overwrite", action="store_true", help="overwrite existing file (default: keep both)")
    p.add_argument("--timeout", type=int, default=0, help="minutes before giving up (0 = no limit)")
    p.add_argument("--progress", action="store_true", help="live progress line")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG_DIR, help=argparse.SUPPRESS)
    p.set_defaults(func=cmdDownload)

    p = sub.add_parser("daemon", help="run headless daemon with aria2-compatible RPC")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG_DIR, help=argparse.SUPPRESS)
    p.add_argument("-o", "--output", help="default download folder")
    p.set_defaults(func=cmdDaemon)

    p = sub.add_parser("rpc", help="control a running daemon")
    p.add_argument("rpc_command", choices=["add", "list", "pause", "resume", "status", "shutdown"])
    p.add_argument("target", nargs="?", default=None,
                   help="URL for add, gid for pause/resume/status")
    p.add_argument("-o", "--output", help="output folder (add)")
    p.add_argument("-N", "--name", help="filename (add)")
    p.add_argument("--rpc-port", type=int, default=DEFAULT_RPC_PORT)
    p.add_argument("--rpc-token", default="")
    p.set_defaults(func=cmdRpc)
    return parser


def main(argv=None) -> int:
    args = buildParser().parse_args(argv)
    if args.command == "rpc":
        needsTarget = {"add"} if False else {"pause", "resume", "status"}
        if args.rpc_command in needsTarget and not args.target:
            print(f"gd-cli rpc {args.rpc_command} requires a gid", file=sys.stderr)
            return 2
        if args.rpc_command == "add" and (not args.target or not args.target.startswith("http")):
            print("gd-cli rpc add requires a URL", file=sys.stderr)
            return 2
    return args.func(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
