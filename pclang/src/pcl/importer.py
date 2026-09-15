"""importer — .pcl 模块化互操作（DSL §9.3，DESIGN §3/A11/A12）。

- ``install_importer()``：meta path finder（追加在 PathFinder 之后）——
  仅当常规路径查找失败（返回 None）时才接手查找 ``<name>.pcl``，
  因此同名 ``.py`` 天然优先、不遮蔽既有 Python；
- ``pcl.import_module(name)``：免装 hook 的程序化导入（注册 sys.modules）；
- ``import_from_path(path)``：run 专用——每次加载**全新模块实例**
  （唯一模块名、不入 sys.modules；缓存与 .pyc 复用不受影响）。

加载走 importlib（spec_from_file_location + SourceFileLoader）→ 真正复用/生成
``.pyc``；模块 ``__file__`` 按源 ``.pcl`` 位置设置（相对 import 按源目录解析，
``__package__`` 由 import 系统按模块名推导）；``__pcl_source__`` 注入。
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import importlib.util
import sys
import types
from itertools import count
from pathlib import Path

from .compiler import CompiledCode, CompiledFile, ensure_compiled
from .errors import PclCompileError

_SEQ = count(1)


class PclLoader(importlib.abc.Loader):
    """按源 .pcl 路径加载（生成源在缓存文件；co_filename 指向缓存 → traceback 可读）。"""

    def __init__(self, fullname: str, pcl_path: Path,
                 *, cache_dir: str | None = None):
        self.fullname = fullname
        self.pcl_path = Path(pcl_path)
        self.cache_dir = cache_dir

    def create_module(self, spec):
        return None  # 常规模块

    def exec_module(self, module):
        try:
            compiled = ensure_compiled(self.pcl_path, cache_dir=self.cache_dir)
        except PclCompileError as e:
            raise ImportError(
                f"无法导入 {self.fullname}（{self.pcl_path}）：{e.format()}") from None
        code, gen_path = _load_code(compiled, self.fullname)
        exec(code, module.__dict__)
        # __file__ 等按源 .pcl 位置覆写（§5.3）；co_filename 仍指向缓存文件
        module.__file__ = str(self.pcl_path)
        module.__pcl_source__ = str(self.pcl_path)
        module.__pcl_genfile__ = str(gen_path)
        if isinstance(compiled, CompiledFile):
            try:
                module.__cached__ = importlib.util.cache_from_source(str(compiled.cache_py))
            except Exception:
                module.__cached__ = None

    def get_source(self, fullname) -> str:
        compiled = ensure_compiled(self.pcl_path, cache_dir=self.cache_dir)
        if isinstance(compiled, CompiledFile):
            return compiled.cache_py.read_text(encoding="utf-8")
        return compiled.source

    def is_package(self, fullname) -> bool:
        return False


def _load_code(compiled, name: str):
    """CompiledFile → importlib 加载（复用 .pyc）；CompiledCode → 内存 compile。"""
    if isinstance(compiled, CompiledFile):
        loader = importlib.machinery.SourceFileLoader(name, str(compiled.cache_py))
        return loader.get_code(name), compiled.cache_py
    assert isinstance(compiled, CompiledCode)
    return (compile(compiled.source, compiled.display_name, "exec"),
            compiled.display_name)


class _PclMetaFinder(importlib.abc.MetaPathFinder):
    """追加在 PathFinder 之后的兜底查找器：仅接手常规查找失败的 ``name.pcl``。"""

    def find_spec(self, fullname, path=None, target=None):
        modname = fullname.rpartition(".")[2]
        for d in (path if path is not None else sys.path):
            if not d:
                continue
            try:
                candidate = Path(d) / f"{modname}.pcl"
                if candidate.is_file():
                    loader = PclLoader(fullname, candidate)
                    return importlib.util.spec_from_file_location(
                        fullname, candidate, loader=loader)
            except OSError:
                continue
        return None


_finder = None


def install_importer() -> None:
    """注册 .pcl import hook（幂等；只注册、不改 sys.path）。"""
    global _finder
    if _finder is not None and any(
            isinstance(f, _PclMetaFinder) for f in sys.meta_path):
        return
    _finder = _PclMetaFinder()
    sys.meta_path.append(_finder)


def import_module(name: str, *, cache_dir: str | None = None):
    """程序化导入 .pcl（免装 hook）；注册 sys.modules（正常模块缓存语义）。"""
    if name in sys.modules:
        return sys.modules[name]
    finder = _PclMetaFinder()
    spec = finder.find_spec(name)
    if spec is None:
        raise ModuleNotFoundError(f"找不到 .pcl 模块 {name!r}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def import_from_path(path, *, cache_dir: str | None = None, no_cache: bool = False):
    """run_program 专用：每次加载全新模块实例（唯一名、不入 sys.modules）。"""
    pcl_path = Path(path)
    compiled = ensure_compiled(pcl_path, cache_dir=cache_dir, no_cache=no_cache)
    name = f"_pcl_run_{next(_SEQ)}"
    code, gen_path = _load_code(compiled, name)
    module = types.ModuleType(name)
    module.__dict__.update({
        "__name__": name,
        "__loader__": None,
        "__spec__": None,
        "__file__": str(pcl_path),
        "__pcl_source__": str(pcl_path),
        "__pcl_genfile__": str(gen_path),
    })
    if isinstance(compiled, CompiledCode):
        module.__pcl_gensource__ = compiled.source
    exec(code, module.__dict__)
    return module
