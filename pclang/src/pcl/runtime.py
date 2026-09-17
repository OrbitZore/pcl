"""runtime — 运行时 API 与 Run 执行环境（RFC 0001 §6，RFC 0000 §9.1/§10）。

生成代码视角的 8 个入口：emit / text / submit / save / load / new_ctx /
push_sink / pop_sink（+ 内部 ``__pcl_freeze``）。

- 一切状态收敛在 ``Run`` 对象（contextvar 定位当前 Run；多 run 并存，A12）；
- 无 Run 上下文调用任何运行时函数 → R405；
- ``text()`` 按 RFC 0000 §10 规则字符串化；``__pcl_freeze`` 转 JSON-safe 值。
"""

from __future__ import annotations

import contextvars
import json
import math
from collections.abc import Callable
from typing import Any

from .bridge import PassResult, make_bridge
from .errors import PclCompileError, PclError

# submit 前对 prompt 做 ASCII 空白双端剥除（RFC 0000 §7；全角空白不剥）
_TRIM_WS = " \t\n\r\f\v"

# 写回值 JSON 反序列化深度上限（RFC 0001 §6）
_MAX_JSON_DEPTH = 32


# ---- text() 与 :read 冻结（RFC 0000 §10） --------------------------------------

def _freeze_value(v: Any, _seen: frozenset[int] | None = None) -> Any:
    """按 text() 同套规则转出 JSON-safe 值（容器结构保留，§7）。

    - str/None/bool/int → 原样；float 有限 → 原样，NaN/Infinity → str() 兜底；
    - dict/list/tuple → 递归同构；非字符串键 int/float/bool/None 按 JSON 惯例
      字符串化、其余 str() 兜底后作键，键碰撞 → 整体退化 str(v)；
    - 其余对象 → str() 兜底；循环引用 → str(v) 兜底。
    """
    seen = _seen or frozenset()
    if isinstance(v, str):
        return v
    if v is None or isinstance(v, bool) or isinstance(v, int):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else str(v)
    if isinstance(v, (list, tuple)):
        if id(v) in seen:
            return str(v)
        nxt = seen | {id(v)}
        return [_freeze_value(x, nxt) for x in v]
    if isinstance(v, dict):
        if id(v) in seen:
            return str(v)
        nxt = seen | {id(v)}
        out: dict[str, Any] = {}
        for k, val in v.items():
            ks = _dict_key(k)
            if ks in out:
                return str(v)  # 键字符串化碰撞：整体退化（§10）
            out[ks] = _freeze_value(val, nxt)
        return out
    return str(v)


def _dict_key(k: Any) -> str:
    if isinstance(k, str):
        return k
    if k is True:
        return "true"
    if k is False:
        return "false"
    if k is None:
        return "null"
    if isinstance(k, int):
        return str(k)
    if isinstance(k, float):
        if not math.isfinite(k):
            return str(k)
        return repr(k)
    return str(k)


def text(v: Any) -> str:
    """RFC 0000 §10 字符串化。

    str → 原样；dict/list/tuple → 紧凑 JSON（键按插入序，tuple 视作 list，
    不可 JSON 化的值与 NaN/Infinity 以 str() 兜底，整体失败退化 str(v)）；
    bool → true/false；None → null；int → 十进制；float → round-trip repr；
    其余对象 → str(v)。
    """
    if isinstance(v, str):
        return v
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, (dict, list, tuple)):
        frozen = _freeze_value(v)
        if isinstance(frozen, str):
            return frozen  # 整体退化（键碰撞/循环引用等）：冻结层已给出 str(v)
        try:
            return json.dumps(frozen, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError, RecursionError):
            return str(v)
    return str(v)


def __pcl_freeze(v: Any) -> Any:
    """:read 快照冻结（生成代码按需导入；RFC 0000 §7）。"""
    return _freeze_value(v)


# ---- Run ----------------------------------------------------------------

class RunResult:
    """run_program 的返回：输出文档全文 + 本次运行的新模块实例。"""

    __slots__ = ("output", "module")

    def __init__(self, output: str, module):
        self.output = output
        self.module = module


class Run:
    """一次执行环境：sink 栈、桥接、输出通道、中止标志。"""

    def __init__(self, bridge=None, *, agent: str | None = None,
                 out: Callable[[str], None] | None = None, trace=None):
        if bridge is None:
            bridge = make_bridge(agent or "null")
        self.bridge = bridge
        self.out = out
        self.trace = trace
        self.sinks: list[list[str]] = []
        self._output: list[str] = []
        self.aborted = False
        self._token = None

    def __enter__(self) -> Run:
        try:
            self.bridge.start()
        except BaseException:
            self.bridge.close()   # start 失败不进 __exit__，主动清理子进程资源
            raise
        self._token = _current_run.set(self)
        return self

    def __exit__(self, *exc) -> bool:
        _current_run.reset(self._token)
        self.bridge.close()
        return False

    @property
    def output(self) -> str:
        return "".join(self._output)

    def emit(self, s: str):
        if self.sinks:
            self.sinks[-1].append(s)
        else:
            self._output.append(s)
            if self.out is not None:
                self.out(s)

    def abort(self):
        self.aborted = True
        self.bridge.abort()


_current_run: contextvars.ContextVar[Run | None] = contextvars.ContextVar(
    "pcl_current_run", default=None)


def _require_run() -> Run:
    run = _current_run.get()
    if run is None:
        raise PclError("R405", "运行时函数在无 Run 上下文处被调用（需 with Run(...)）")
    return run


# ---- 生成代码入口（8 名 + 内部冻结） --------------------------------------

def emit(s: str) -> None:
    """追加当前 sink（pass 体内 = prompt 缓冲）。"""
    _require_run().emit(s)


def push_sink() -> None:
    """（内部）压入输出缓冲栈。"""
    _require_run().sinks.append([])


def pop_sink() -> str:
    """（内部）弹出并返回缓冲栈顶。"""
    run = _require_run()
    return "".join(run.sinks.pop())


def _depth(v: Any, d: int = 1) -> int:
    if isinstance(v, (dict, list, tuple)):
        child = max((_depth(x, d + 1) for x in
                     (v.values() if isinstance(v, dict) else v)), default=d)
        return child
    return d


def submit(prompt: str, reads: dict | None = None,
           writes: tuple[str, ...] = ()) -> PassResult:
    """提交一轮 pass（RFC 0000 §7）。

    - prompt 先 ASCII 空白双端 trim；trim 后为空 → 跳过桥接、返回空结果；
    - 越权写入 → R406（先于空回复判定）；空回复 → A504；
    - 写回值深度 > 32 → R400。
    """
    run = _require_run()
    p = prompt.strip(_TRIM_WS)
    if not p:
        return PassResult("", {})
    allowed = tuple(writes)
    result = run.bridge.submit(p, reads or {}, allowed)
    unauthorized = {k for k in result.writes if k not in allowed}
    if unauthorized:
        if len(allowed) == 1 and unauthorized == set(result.writes.keys()):
            # 自动包装：agent 平铺写 dict（如 {"all":[…],"pending":[…]}）而非
            # 嵌套进唯一授权名——将整个写入包装为 {授权名: {平铺 dict}}
            result = PassResult(result.reply, {allowed[0]: dict(result.writes)})
        else:
            bad = ", ".join(sorted(unauthorized))
            raise PclError(
                "R406", f"agent 写入 :write 之外的名字：{bad}")
    for name, value in result.writes.items():
        d = _depth(value)
        if d > _MAX_JSON_DEPTH:
            raise PclError(
                "R400", f"写回值 {name!r} 反序列化深度 {d} 超过上限 {_MAX_JSON_DEPTH}")
    if result.reply == "":
        raise PclError("A504", "agent 无有效回复（宁报错不静默）")
    return result


def save() -> str:
    """返回当前上下文 token（opaque str）。"""
    return _require_run().bridge.save()


def load(token: str) -> None:
    """切换到 token 对应上下文；非 str → R431。"""
    if not isinstance(token, str):
        raise PclError("R431", f":load 变量值非 str：{type(token).__name__}")
    _require_run().bridge.load(token)


def new_ctx() -> None:
    """新建匿名上下文并切换。"""
    _require_run().bridge.new_ctx()


def context(text: str) -> None:
    """上下文注入 ``$(@ … @)``：独立用户消息注入 agent 会话，不触发推理。"""
    _require_run().bridge.context(text)


def note(text: str) -> None:
    """注记 ``$(# …)``：桥接层支持（嵌入形态）则下发为会话 custom 条目，
    否则（独立运行）渲染进输出文档——两种形态均不进 LLM 上下文。"""
    run = _require_run()
    if not run.bridge.note(text):
        run.emit(text)


# ---- run_program（公共 API，RFC 0001 §6） ----------------------------------

def _parse_pcl_annotations(source: str) -> dict[int, int]:
    """解析生成源逐行尾注 ``# pcl:N`` / ``# pcl:N-M`` → {生成行: 模板行}。"""
    import re

    ann = {}
    pat = re.compile(r"# pcl:(\d+)(?:-(\d+))?\s*$")
    for i, line in enumerate(source.split("\n"), 1):
        m = pat.search(line)
        if m:
            ann[i] = int(m.group(1))
    return ann


def _module_annotations(module) -> dict[int, int]:
    src = getattr(module, "__pcl_gensource__", None)
    if src is None:
        gen = getattr(module, "__pcl_genfile__", None)
        if gen:
            try:
                with open(gen, encoding="utf-8") as f:
                    src = f.read()
            except OSError:
                return {}
        else:
            return {}
    return _parse_pcl_annotations(src)


def _translate_runtime_error(exc: BaseException, module, pcl_path) -> PclError:
    """R400 包装：traceback 帧映射回 .pcl 行（RFC 0000 §11）。"""
    import os

    gen_path = str(getattr(module, "__pcl_genfile__", ""))
    pcl_src = getattr(module, "__pcl_source__", str(pcl_path))
    ann = _module_annotations(module)
    frames = []
    tpl_line = None
    tb = exc.__traceback__
    while tb is not None:
        co = tb.tb_frame.f_code
        if co.co_filename == gen_path:
            gl = tb.tb_lineno
            t = ann.get(gl)
            frames.append(f"  {os.path.basename(gen_path)}:{gl} → "
                          f"{os.path.basename(pcl_src)}:{t if t is not None else '?'}")
            if t is not None:
                tpl_line = t   # 逐帧更新：最内层（错误源）胜出
        tb = tb.tb_next
    msg = f"{type(exc).__name__}: {exc}"
    if frames:
        msg = "\n".join([msg, *frames[-5:]])
    return PclError("R400", msg, file=str(pcl_path),
                    line=tpl_line or 1, col=1)


def run_program(path, prompt: str = "", *, agent: str = "pi",
                script=None, var_overrides: dict | None = None,
                cache_dir: str | None = None, no_cache: bool = False,
                out=None, timeout: float | None = None, trace: bool = False,
                pi_bin=None, connector_path=None, pi_args=None) -> RunResult:
    """加载入口模块（新实例）→ 注入 --var → with Run: main(prompt)。

    - 入口 .pcl 所在目录（realpath）插入 sys.path[0]（幂等、不回滚，§9.3）；
    - --var 注入时点：加载层之后、main 之前（保留名拦截，§6）；
    - 模板体异常 → R400（traceback 帧回译）；PclError 原样上抛。
    """
    import keyword as _kw
    import sys as _sys
    from pathlib import Path as _Path

    from .bridge import make_bridge as _make_bridge
    from .importer import import_from_path as _import_from_path
    from .importer import install_importer as _install_importer
    from .tparse import RUNTIME_RESERVED as _RESERVED

    # pcl run 内建 importer hook（RFC 0001 §3）：`${import helpers}` 等
    # DSL→DSL 导入经 sys.path[0]（源目录）解析——不依赖宿主预先 install_importer
    _install_importer()

    pcl_path = _Path(path)
    if not pcl_path.exists():
        raise PclError("R400", f"模板文件不存在：{pcl_path}")
    src_dir = str(pcl_path.resolve().parent)
    if src_dir not in _sys.path:
        _sys.path.insert(0, src_dir)

    # --var 保留名拦截（额外拦 main/prompt，严于绑定目标规则，§6）
    for k in (var_overrides or {}):
        if not k.isidentifier() or _kw.iskeyword(k):
            raise PclCompileError(
                "C300", f"--var 名 {k!r} 不是合法 Python 标识符",
                file=str(pcl_path), line=1, col=1)
        if k in _RESERVED or k in ("main", "prompt") or k.startswith("__pcl_"):
            raise PclCompileError(
                "C300", f"--var 名 {k!r} 命中保留名", file=str(pcl_path), line=1, col=1)

    mod = _import_from_path(pcl_path, cache_dir=cache_dir, no_cache=no_cache)
    for k, v in (var_overrides or {}).items():
        setattr(mod, k, v)

    bridge = _make_bridge(agent, script=script, pi_bin=pi_bin,
                          connector_path=connector_path, pi_args=pi_args,
                          timeout=timeout, trace=trace)
    with Run(bridge=bridge, out=out) as run:
        try:
            mod.main(prompt)
        except PclError:
            raise
        except KeyboardInterrupt:
            raise
        except BaseException as e:  # R400 包装
            raise _translate_runtime_error(e, mod, pcl_path) from None
    return RunResult(run.output, mod)
