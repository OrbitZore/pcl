"""pytest 共享夹具。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# 测试期隔离默认缓存目录（避免污染 ~/.cache/pcl）
os.environ.setdefault("XDG_CACHE_HOME", tempfile.mkdtemp(prefix="pcl-test-xdg-"))

DATA = Path(__file__).resolve().parent / "data"


@pytest.fixture
def data_dir() -> Path:
    return DATA


@pytest.fixture
def tmp_pcl(tmp_path: Path):
    """写入临时 .pcl 并返回路径。"""

    def write(source: str, name: str = "t.pcl") -> Path:
        p = tmp_path / name
        p.write_text(source, encoding="utf-8")
        return p

    return write
