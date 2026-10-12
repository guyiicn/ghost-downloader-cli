"""Headless runner: asyncio loop on a background thread + upstream CoroutineRunner.

Mirrors what upstream `app.startup.createEngine` does with QTimer, but without Qt.
"""
from __future__ import annotations

import asyncio
import threading

from cli.stubs import _install as _ensureStubs

_ensureStubs()  # noqa: E402  (must precede app.* imports)

from app.services.coroutine_runner import CoroutineRunner  # noqa: E402


def createRunner() -> CoroutineRunner:
    try:
        from uvloop import new_event_loop
    except ImportError:
        new_event_loop = asyncio.new_event_loop

    loop = new_event_loop()

    def dispatch(fn) -> None:
        if asyncio.iscoroutine(fn):
            asyncio.run_coroutine_threadsafe(fn, loop)
        else:
            loop.call_soon_threadsafe(fn)

    runner = CoroutineRunner(dispatch, loop=loop)
    threading.Thread(target=loop.run_forever, daemon=True, name="gd-cli-loop").start()
    return runner
