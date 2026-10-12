"""Minimal stand-ins for PySide6 bits the headless CLI doesn't need.

Import this BEFORE any `app.*` module so `app.config.paths` and friends
see a harmless Qt shim instead of the real toolkit.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path


def _install(force: bool = False) -> None:
    if "PySide6" in sys.modules and not force:
        return

    # Real PySide6 present: only add the pieces headless needs that stubs
    # replace (nothing to do — real Qt works fine without QApplication).
    try:
        import PySide6.QtCore  # noqa: F401
        import shiboken6  # noqa: F401
        return
    except ImportError:
        pass

    pyside6 = types.ModuleType("PySide6")
    QtCore = types.ModuleType("PySide6.QtCore")

    class QStandardPaths:
        class StandardLocation:
            GenericDataLocation = "GenericDataLocation"
            DownloadLocation = "DownloadLocation"  # headless: will be overridden by path

        @staticmethod
        def writableLocation(kind: str) -> str:
            # Headless data dir: ~/.local/share/ghost-downloader-cli
            return str(Path.home() / ".local" / "share" / "ghost-downloader-cli")

    class QFileSystemWatcher:
        def __init__(self, *args, **kwargs) -> None: ...

    class QResource:
        @staticmethod
        def registerResource(*args, **kwargs) -> bool:
            return True

    QtCore.QStandardPaths = QStandardPaths
    QtCore.QFileSystemWatcher = QFileSystemWatcher
    QtCore.QResource = QResource
    pyside6.QtCore = QtCore
    sys.modules["PySide6"] = pyside6
    sys.modules["PySide6.QtCore"] = QtCore

    # shiboken6.isValid() — used by upstream to guard QObject lifetime.
    shiboken6 = types.ModuleType("shiboken6")
    shiboken6.isValid = lambda _obj: True
    sys.modules["shiboken6"] = shiboken6


_install()
