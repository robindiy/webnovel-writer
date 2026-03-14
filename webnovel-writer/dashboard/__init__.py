# Webnovel Dashboard - 可视化小说管理面板

import sys
from pathlib import Path


_PACKAGE_DIR = Path(__file__).resolve().parent
for _base in (_PACKAGE_DIR, *_PACKAGE_DIR.parents):
    _pydeps = _base / ".pydeps"
    if _pydeps.is_dir():
        _pydeps_str = str(_pydeps)
        if _pydeps_str not in sys.path:
            sys.path.insert(0, _pydeps_str)
        break
