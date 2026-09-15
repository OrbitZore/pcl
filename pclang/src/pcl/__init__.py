"""pcl — Prompt Control Language（模板层 PCL，脚本层 Python）。

公共 API（DESIGN §6/A12）：
- ``compile_program(path) -> str``：编译返回生成源文本，不执行；
- ``run_program(path, prompt, *, agent=...) -> RunResult``：完整执行；
- ``Run / RunResult / PassResult / PclError / PclCompileError``；
- ``install_importer()`` / ``import_module(name)``：.pcl 模块化互操作。

重导出经 ``__getattr__`` 懒加载（``import pcl.runtime`` 保持轻量，
生成代码不因包初始化拖入编译器链）。
"""

from __future__ import annotations

from ._version import __version__
from .errors import PclCompileError, PclError

__all__ = [
    "__version__",
    "PclError", "PclCompileError",
    "compile_program", "run_program",
    "Run", "RunResult", "PassResult",
    "install_importer", "import_module", "text",
]

_LAZY = {
    "compile_program": ("pcl.compiler", "compile_program"),
    "run_program": ("pcl.runtime", "run_program"),
    "Run": ("pcl.runtime", "Run"),
    "RunResult": ("pcl.runtime", "RunResult"),
    "PassResult": ("pcl.bridge", "PassResult"),
    "install_importer": ("pcl.importer", "install_importer"),
    "import_module": ("pcl.importer", "import_module"),
    "text": ("pcl.runtime", "text"),
}


def __getattr__(name: str):
    if name in _LAZY:
        import importlib

        mod, attr = _LAZY[name]
        return getattr(importlib.import_module(mod), attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(__all__)
