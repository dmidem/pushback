"""
pushback — SSH/rsync-based backup tool.

Copyright (c) 2025 Dmitry Demin
Licensed under Apache-2.0 OR MIT
"""

from __future__ import annotations

import sys

from ._meta import APP_NAME, MIN_PYTHON, VERSION

__version__ = VERSION

_min_major, _min_minor = (int(x) for x in MIN_PYTHON.split(".", 1))
if (sys.version_info.major, sys.version_info.minor) < (_min_major, _min_minor):
    _py = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    raise SystemExit(f"{APP_NAME} requires Python >= {MIN_PYTHON} (got {_py})")

__all__ = ["APP_NAME", "__version__", "MIN_PYTHON"]
