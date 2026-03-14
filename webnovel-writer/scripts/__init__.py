"""
webnovel-writer scripts package

This package contains all Python scripts for the webnovel-writer plugin.
"""

import sys
from pathlib import Path

__version__ = "5.4.0"
__author__ = "lcy"

_PACKAGE_DIR = Path(__file__).resolve().parent
if str(_PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_DIR))

for _base in (_PACKAGE_DIR, *_PACKAGE_DIR.parents):
    _pydeps = _base / ".pydeps"
    if _pydeps.is_dir():
        _pydeps_str = str(_pydeps)
        if _pydeps_str not in sys.path:
            sys.path.insert(0, _pydeps_str)
        break

# Expose main modules
from . import security_utils
from . import project_locator
from . import chapter_paths

__all__ = [
    "security_utils",
    "project_locator",
    "chapter_paths",
]
