from __future__ import annotations

import sys

from ._meta import APP_DESCRIPTION, APP_NAME, HOMEPAGE, LICENSE, MIN_PYTHON, VERSION

__doc__ = (
    f"""
{APP_NAME} — {APP_DESCRIPTION}

SPDX-License-Identifier: {LICENSE}
"""
).strip()


__version__ = VERSION

_min_major, _min_minor = (int(x) for x in MIN_PYTHON.split(".", 1))
if (sys.version_info.major, sys.version_info.minor) < (_min_major, _min_minor):
    _py = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    raise SystemExit(f"{APP_NAME} requires Python >= {MIN_PYTHON} (got {_py})")

__all__ = [
    "APP_DESCRIPTION",
    "APP_NAME",
    "VERSION",
    "LICENSE",
    "HOMEPAGE",
    "MIN_PYTHON",
]
