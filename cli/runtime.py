"""Locate the upstream engine in dev (source tree) and installed (site-packages) modes.

The upstream code is vendored under upstream/ in the repo. When this package is
pip-installed, setup.py maps upstream/app -> top-level `app` and
upstream/features -> top-level `features` inside site-packages, so plain
imports work. In a source checkout neither is importable, so we put the
upstream dirs on sys.path instead.
"""
from __future__ import annotations

import sys
from pathlib import Path


def resolveFeaturesDir() -> Path:
    """Return the features directory the upstream pack loader should scan.

    Also guarantees `import app` works afterwards (source-tree mode adds
    upstream/ to sys.path as a side effect).
    """
    try:  # installed mode
        import features as _features  # noqa: PLC0415
        return Path(_features.__file__).resolve().parent
    except ImportError:
        pass

    upstream = Path(__file__).resolve().parent.parent / "upstream"
    if not (upstream / "app").is_dir():
        raise RuntimeError(
            "upstream engine not found: neither pip-installed nor a source checkout "
            "with upstream/ next to cli/"
        )
    for p in (upstream, upstream / "features"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    return upstream / "features"
