"""Engine assembly for headless mode (no Qt app, no GUI)."""
from __future__ import annotations

import signal
import threading
from pathlib import Path

from cli.runner import createRunner
from cli.runtime import resolveFeaturesDir
from cli.stubs import _install as _ensureStubs

_ensureStubs()  # noqa: E402  (must precede app.* imports)


def createEngine(configFolder: Path | None = None, downloadFolder: Path | None = None):
    """Build the upstream Engine wired for headless operation.

    - config lives in ~/.config/ghost-downloader-cli/config.json (or --config dir)
    - aria2-compatible RPC listener is always on (default port 16800)
    - browser-extension listener stays off
    """
    # Resolve packs dir and make `import app` work BEFORE anything imports
    # app.engine (feature_service binds paths.FEATURES_DIR at import time).
    featuresDir = resolveFeaturesDir()
    import app.config.paths as _paths
    _paths.FEATURES_DIR = featuresDir

    from app.config.cfg import cfg
    from app.engine import Engine
    from app.loader import seedPacks
    from app.models.pack import PackConfig, PackServices
    from app.services.update_service import installPendingPacks
    from app.signal import Signal

    if configFolder is not None:
        configFolder.mkdir(parents=True, exist_ok=True)
        cfg.file = configFolder / "config.json"
    cfg.load()

    if downloadFolder is not None:
        cfg.downloadFolder.value = str(downloadFolder)
    # Headless defaults: RPC on, browser extension off.
    cfg.isAria2RpcEnabled.value = True
    cfg.isBrowserExtensionEnabled.value = False

    # Extend upstream aria2 RPC with pause/unpause/tellStatus/shutdown.
    from cli.patch_rpc import patch_aria2_rpc
    patch_aria2_rpc()

    runner = createRunner()

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
    # Let the patched RPC methods reach the task store.
    engine.aria2RpcService._taskService = engine.taskService

    # Feature packs. BT/ed2k may fail on missing optional deps (libtorrent) —
    # upstream logs a warning and skips, which is fine headless.
    services = PackServices(coroutineRunner=runner, speedMeter=engine.speedMeter)
    installPendingPacks(featuresDir)
    seedPacks(featuresDir, featuresDir)  # same dir → no-op
    engine.featureService.load(services)
    PackConfig.load()

    engine.start()
    return engine, runner


def waitForever() -> None:
    """Block until SIGINT/SIGTERM, like a well-behaved daemon."""
    done = threading.Event()

    def _handle(_signum, _frame):
        done.set()

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)
    try:
        while not done.is_set():
            done.wait(timeout=3600)
    except KeyboardInterrupt:
        pass
