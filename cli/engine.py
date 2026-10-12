"""Engine assembly for headless mode (no Qt app, no GUI)."""
from __future__ import annotations

import signal
import sys
from pathlib import Path

from cli.runner import createRunner
from cli.stubs import _install as _ensureStubs

_ensureStubs()  # noqa: E402


def createEngine(configFolder: Path | None = None, downloadFolder: Path | None = None):
    # Ensure upstream/features is discoverable.  In headless mode EXECUTABLE_DIR
    # is Path(".") so FEATURES_DIR resolves to CWD/features.  Symlink there to
    # upstream/features so seedPacks/loadPacks find the packs.
    cwd_features = Path.cwd() / "features"
    if not cwd_features.is_dir():
        upstream_features = Path(__file__).resolve().parent.parent / "upstream" / "features"
        if upstream_features.is_dir():
            try:
                cwd_features.symlink_to(upstream_features)
            except FileExistsError:
                pass
    """Build an upstream Engine wired for headless operation.

    - config lives in ~/.config/ghost-downloader-cli/config.json (or --config dir)
    - aria2-compatible RPC listener is always enabled (default port 16800)
    - browser-extension listener stays off
    """
    from qfluentwidgets import qconfig

    from app.config.cfg import cfg
    from app.config.paths import FEATURES_DIR as _FEAT
    from app.engine import Engine
    from app.models.pack import PackConfig, PackServices
    from app.loader import seedPacks
    from app.services.feature_service import FeatureService
    from app.services.runtime_status import RuntimeStatusService
    from app.services.update_service import installPendingPacks
    from app.signal import Signal

    # In headless mode FEATURES_DIR resolves to CWD/features (EXECUTABLE_DIR).
    # Override to point at upstream/features so seedPacks/loadPacks actually finds packs.
    import app.config.paths as _paths
    _paths.FEATURES_DIR = _FEAT.parent / "features"
    FEATURES_DIR = _paths.FEATURES_DIR  # re-export for callers

    if configFolder is not None:
        configFolder.mkdir(parents=True, exist_ok=True)
        cfg.file = configFolder / "config.json"
    cfg.load()

    if downloadFolder is not None:
        cfg.downloadFolder.value = str(downloadFolder)
    # Headless defaults: RPC on, browser extension off.
    cfg.isAria2RpcEnabled.value = True
    cfg.isBrowserExtensionEnabled.value = False

    runner = createRunner()

    # Patch upstream aria2_rpc.py to support pause/unpause/tellStatus/shutdown
    from cli.patch_rpc import patch_aria2_rpc
    patch_aria2_rpc()

    class _NoWatcher:
        fileChanged = Signal()

        @staticmethod
        def addPath(_path) -> bool:
            return True

        @staticmethod
        def removePath(_path) -> bool:
            return True

    def noop(*args, **kwargs) -> None:
        return None

    engine = Engine(runner, fileWatcher=_NoWatcher(), loadCrx=None, extensionFolder=None,
                    deleteRecoverably=noop)
    # Patch Aria2RpcService to also hold taskService reference (for pause/tellStatus)
    engine.aria2RpcService._taskService = engine.taskService

    # Feature packs (http/bilibili/bittorrent/...). BT/ed2k may fail to import
    # optional deps — upstream loader logs a warning and skips, which is fine.
    services = PackServices(coroutineRunner=runner, speedMeter=engine.speedMeter)
    installPendingPacks(FEATURES_DIR)
    seedPacks(FEATURES_DIR, FEATURES_DIR)
    engine.featureService.load(services)
    PackConfig.load()

    engine.start()
    return engine, runner


def waitForever() -> None:
    """Block until SIGINT/SIGTERM, like a well-behaved daemon."""
    stop = signal.Event() if hasattr(signal, "Event") else None
    import threading

    done = threading.Event()

    def _handle(signum, _frame):
        done.set()

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)
    try:
        while not done.is_set():
            done.wait(timeout=3600)
    except KeyboardInterrupt:
        pass
