"""compiler — 编译管线与生成源缓存（DESIGN §5.3 / A11）。

- ``compile_source``：模板文本 → 生成 Python 源（含 ``compile()`` 语法检查 → C310）；
- ``compile_file``：读取（UTF-8、BOM 剥除 → L102）→ compile_source；
- ``ensure_compiled``：缓存命中直接复用；未命中编译后经临时文件 + ``os.replace``
  原子落盘 ``<缓存根>/pcl/<stem>-<sha8>.pcl.py``（sha 含编译器版本）；
  同 stem 仅保留最近 2 个条目（陈旧随写随删）；
- ``--cache none``：不落盘，compile() 用虚拟名 ``<stem>.pcl.py``。
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import pygen, tlex, tparse
from ._version import COMPAT_VERSION, __version__
from .errors import PclCompileError


def compile_source(src: str, filename: str) -> pygen.GenResult:
    """模板源文本 → 生成源（GenResult）；编译期错误以 PclCompileError 抛出。"""
    tokens = tlex.tokenize(src, filename)
    nodes = tparse.parse(tokens, filename)
    gen = pygen.generate(nodes, filename, version=__version__)
    # 生成源语法检查（C310，映射行号后报告）
    try:
        compile(gen.source, gen.display_name, "exec")
    except SyntaxError as exc:
        lineno = exc.lineno or 1
        tpl = _translate_line(gen.line_map, lineno)
        raise PclCompileError(
            "C310", f"生成代码未通过 Python 编译：{exc.msg}（生成源第 {lineno} 行）",
            file=filename, line=tpl or 1, col=1,
        ) from None
    return gen


def compile_file(path: Path) -> pygen.GenResult:
    """读取 .pcl（L102）→ compile_source。"""
    try:
        data = path.read_bytes()
    except OSError as e:
        raise PclCompileError("L102", f"无法读取源文件：{e}",
                              file=str(path), line=1, col=1) from None
    try:
        src = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise PclCompileError("L102", f"源文件不是合法 UTF-8：{e}",
                              file=str(path), line=1, col=1) from None
    if src.startswith("\ufeff"):
        src = src[1:]  # UTF-8 BOM 剥除（§4.1）
    return compile_source(src, str(path))


def compile_program(path, *, cache_dir: str | None = None,
                   no_cache: bool = False) -> str:
    """公共 API：编译返回生成源文本，不执行（缓存照常，§6）。"""
    compiled = ensure_compiled(Path(path), cache_dir=cache_dir, no_cache=no_cache)
    if isinstance(compiled, CompiledCode):
        return compiled.source
    return compiled.cache_py.read_text(encoding="utf-8")


def _translate_line(line_map, gen_line: int) -> int | None:
    if 1 <= gen_line <= len(line_map):
        entry = line_map[gen_line - 1]
        if entry:
            return entry[0]
    return None


# ---- 缓存 ---------------------------------------------------------------

@dataclass
class CompiledFile:
    """缓存命中/落盘形态：加载走 importlib，复用 .pyc。"""

    cache_py: Path
    pcl_path: Path
    gen: pygen.GenResult | None = None   # 本次新生成时携带（缓存命中为 None）


@dataclass
class CompiledCode:
    """--cache none 形态：不落盘，compile() 用虚拟名。"""

    source: str
    display_name: str
    pcl_path: Path


def cache_root(cache_dir: str | None = None) -> Path:
    if cache_dir:
        return Path(cache_dir)
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache")
    return Path(base) / "pcl"


_SAFE_STEM = re.compile(r"[^A-Za-z0-9._-]")


def _stem(path: Path) -> str:
    return _SAFE_STEM.sub("_", path.stem) or "_"


def ensure_compiled(pcl_path: Path, *, cache_dir: str | None = None,
                    no_cache: bool = False) -> CompiledFile | CompiledCode:
    """确保生成源就绪：缓存命中 → CompiledFile；--cache none → CompiledCode。"""
    pcl_path = Path(pcl_path)
    if no_cache:
        gen = compile_file(pcl_path)
        return CompiledCode(gen.source, gen.display_name, pcl_path)

    root = cache_root(cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    data = pcl_path.read_bytes()
    sha = hashlib.sha256(data + __version__.encode() + COMPAT_VERSION.encode()).hexdigest()[:8]
    cache_py = root / f"{_stem(pcl_path)}-{sha}.pcl.py"

    if not cache_py.exists():
        gen = compile_file(pcl_path)
        _atomic_write(cache_py, gen.source)
        _gc_stale(root, _stem(pcl_path), keep=cache_py)
        return CompiledFile(cache_py, pcl_path, gen)
    return CompiledFile(cache_py, pcl_path)


def _atomic_write(path: Path, text: str):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".pcl.py")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _gc_stale(root: Path, stem: str, *, keep: Path):
    """同 stem 仅保留最近 2 个条目（含新写的 keep），更旧的随写随删。"""
    import importlib.util

    try:
        entries = sorted(
            (p for p in root.glob(f"{stem}-*.pcl.py") if p != keep),
            key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for old in entries[1:]:  # 除最新 1 个旧条目外全部删除（含 keep 共保留 2 个）
        try:
            old.unlink()
        except OSError:
            pass
        try:  # 连带清理 __pycache__ 中的对应 .pyc
            pyc = importlib.util.cache_from_source(str(old))
            Path(pyc).unlink(missing_ok=True)
        except Exception:
            pass
