"""
pushback — SSH/rsync-based backup tool.

Copyright (c) 2025 Dmitry Demin
Licensed under Apache-2.0 OR MIT
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("pushback")
except PackageNotFoundError:
    __version__ = "0.0.0+dev"

__all__ = ["__version__"]
