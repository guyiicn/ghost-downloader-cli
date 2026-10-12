"""Packaging: map upstream/app and upstream/features as top-level packages.

All metadata lives in pyproject.toml; this file only exists to express the
package_dir mapping (upstream/app -> `app`, upstream/features -> `features`)
which pyproject.toml's flat [tool.setuptools] config can't do cleanly with
namespace packages.
"""
from setuptools import find_namespace_packages, setup

appPkgs = ["app", *(f"app.{p}" for p in find_namespace_packages("upstream/app"))]
featPkgs = ["features", *(f"features.{p}" for p in find_namespace_packages("upstream/features"))]

setup(
    packages=["cli", *appPkgs, *featPkgs],
    package_dir={"cli": "cli", "app": "upstream/app", "features": "upstream/features"},
    package_data={p: ["*.toml", "*.png", "*.json"] for p in featPkgs},
)
