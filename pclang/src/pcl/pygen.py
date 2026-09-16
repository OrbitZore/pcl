"""pygen — 发射器：AST → Python 源 + genLine→tplLine 映射（DESIGN §5.2）。

发射模型（append + emit）：
- 文本常量按源序追加进单条合并段；
- ``${}`` 发起型：构造即冲刷点（先冲刷、纯语句原样执行、
  表达式语句独立 ``emit(text(EXPR))``，行号 1:1、保序）；
- ``$()`` 合并型：表达式语句立即求值暂存 ``__pcl_tN = text(EXPR)``、
  纯语句立即执行不打断合并段，段在下一冲刷点织成单条 emit、从不冲刷；
- 指令构造（块边界、pass 冻结与开闭/提交序列、reply 发射）与 EOF 均为冲刷点
  （冲刷先于该构造生成的任何代码，含 :if/:while/:for 的条件/迭代式求值）。

模块布局（DSL §9.2）：加载层（:function + 可提升顶层插值）+ ``main(__pcl_prompt="")``
（prompt 序言 + global 并集 + 模板体，源序不变）。
"""

from __future__ import annotations

import ast
import io
import tokenize as _tk

from .tparse import (
    Break,
                     Context,
    Continue,
    For,
    Function,
    If,
    Interp,
    Load,
    NewCtx,
    Note,
    Pass,
    Return,
    Save,
    Text,
    While,
    binding_names,
)

INDENT = "    "


def pystr(s: str) -> str:
    """字符串常量 → 单行转义字面量（R21 转义保真）。

    CPython tokenizer 在字符级规范化源码行结束符（CR LF / CR → LF），
    故含 ``\\r`` 及其他可改写控制字符的常量一律以非 raw 转义形式发射。
    """
    out = ['"']
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\x{ord(ch):02x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _fix_cr(stmt_src: str) -> str:
    """语句源含 CR 时重写字符串常量为非 raw 转义形式（R21）。

    ast.parse/tokenizer 会把三引号字符串内的 CR 归一为 LF（R21 实测：
    ``ast.literal_eval('r\"\"\"a\\r\\nb\"\"\"')`` 得到 'a\\nb'），而 tokenize 的
    token 原文仍保留 CR —— 故从 token 原文手工提取值（``_string_token_value``），
    再以显式 ``\\r`` 转义形式重写（值语义不变）；f-string 等无法安全改写的
    token 原样保留（交由 C310/R400 路径兜底）。
    """
    if "\r" not in stmt_src:
        return stmt_src

    def offset(row, col):
        offs = 0
        for _ in range(row - 1):
            offs = stmt_src.find("\n", offs) + 1
        return offs + col

    out = []
    last = 0
    try:
        for tok in _tk.generate_tokens(io.StringIO(stmt_src).readline):
            if tok.type == _tk.STRING and "\r" in tok.string:
                repl = _escaped_literal(tok.string)
                if repl is None:
                    continue
                start = offset(tok.start[0], tok.start[1])
                end = offset(tok.end[0], tok.end[1])
                out.append(stmt_src[last:start])
                out.append(repl)
                last = end
    except Exception:
        return stmt_src
    out.append(stmt_src[last:])
    return "".join(out)


def _split_string_token(tok_src: str):
    """token 原文 → (prefix_lower, quote, body)；不匹配返回 (None, None, None)。"""
    i = 0
    while i < len(tok_src) and tok_src[i].isalpha():
        i += 1
    prefix = tok_src[:i].lower()
    for q in ('"""', "'''"):
        if tok_src.startswith(q, i) and tok_src.endswith(q) and len(tok_src) >= i + 6:
            return prefix, q, tok_src[i + 3:-3]
    for q in ('"', "'"):
        if tok_src.startswith(q, i) and tok_src.endswith(q) and len(tok_src) >= i + 2:
            return prefix, q, tok_src[i + 1:-1]
    return None, None, None


def _string_token_value(tok_src: str):
    """从 token 原文提取字符串值（不经 ast.parse——其会把 CR 归一为 LF）。

    返回 (value, ok)；f-string 等不支持时 ok=False。
    """
    prefix, quote, body = _split_string_token(tok_src)
    if prefix is None or "f" in prefix:
        return None, False
    if "r" in prefix:
        if "b" in prefix:
            return body.encode("utf-8", "replace"), True
        return body, True
    # 非 raw：token 原文中的裸 CR 与转义序列 CR 同值——先转义再 literal_eval
    safe = prefix + quote + body.replace("\r", "\\r") + quote
    try:
        return ast.literal_eval(safe), True
    except Exception:
        return None, False


def _escaped_literal(tok_src: str) -> str | None:
    """含 CR 的字符串字面量 → 值等价的非 raw 单行转义字面量；不可改写时 None。"""
    value, ok = _string_token_value(tok_src)
    if not ok or value is None:
        return None
    if isinstance(value, bytes):
        return repr(value)
    if not isinstance(value, str):
        return None
    return pystr(value)


def _stmt_src(content: str, st: ast.stmt) -> str:
    seg = ast.get_source_segment(content, st)
    if seg is None:  # pragma: no cover
        raise AssertionError("无法提取语句源码段")
    return _fix_cr(seg)


class GenResult:
    __slots__ = ("source", "display_name", "uses", "line_map")

    def __init__(self, source, display_name, uses, line_map):
        self.source = source
        self.display_name = display_name   # compile() 用的展示文件名
        self.uses = uses
        self.line_map = line_map           # 对齐每行生成源：(tpl_start, tpl_end) 或 None


class _Emitter:
    """子发射器：产出 lines + 逐行 tpl 映射（无绝对行号，组装时拼接）。"""

    def __init__(self):
        self.lines: list[str] = []
        self.tpls: list = []               # 与 lines 对齐：None 或 (tpl, tpl_end)
        self.indent = 0
        self.pending: list[tuple[str, str, int]] = []  # ("c", value, tpl) / ("r", name, tpl)
        self.uses: set[str] = set()
        self._tmp = 0

    # ---- 基础写 ---------------------------------------------------------

    def w(self, code: str, tpl_line: int, tpl_end: int | None = None,
          comment: str | None = None):
        """写一段代码（可为多行 verbatim 语句）；comment 追加在最后一个物理行尾。"""
        if comment is None:
            comment = f"# pcl:{tpl_line}"
        pad = INDENT * self.indent
        chunks = code.split("\n")
        for idx, chunk in enumerate(chunks):
            line = pad + chunk if idx == 0 else chunk
            if idx == len(chunks) - 1 and comment:
                line = f"{line}  {comment}"
            self.lines.append(line)
            self.tpls.append((tpl_line, tpl_end or tpl_line))

    def raw(self, line: str):
        self.lines.append(line)
        self.tpls.append(None)

    # ---- 合并段 ---------------------------------------------------------

    def append_const(self, text: str, tpl_line: int):
        if not text:
            return
        # 不预合并：逐项保留各自模板行，flush 时再合并相邻常量
        # （合并段尾注行区间需覆盖首尾项，DESIGN §5.2）
        self.pending.append(("c", text, tpl_line))

    def append_ref(self, name: str, tpl_line: int):
        self.pending.append(("r", name, tpl_line))

    def flush(self):
        if not self.pending:
            return
        items = self.pending
        self.pending = []
        parts: list[tuple[str, str]] = []
        for kind, val, _ in items:
            if kind == "c":
                if parts and parts[-1][0] == "c":
                    parts[-1] = ("c", parts[-1][1] + val)
                else:
                    parts.append(("c", val))
            else:
                parts.append(("r", val))
        expr = " + ".join(pystr(v) if k == "c" else v for k, v in parts)
        a, b = items[0][2], items[-1][2]
        comment = f"# pcl:{a}" + (f"-{b}" if b > a else "")
        self.uses.add("emit")
        self.w(f"emit({expr})", a, b, comment)

    def tmp(self) -> str:
        self._tmp += 1
        return f"__pcl_t{self._tmp}"

    # ---- 节点发射 -------------------------------------------------------

    def emit_children(self, nodes: list):
        for nd in nodes:
            self.emit_node(nd)

    def emit_node(self, nd):
        if isinstance(nd, Text):
            self.append_const(nd.text, nd.line)
        elif isinstance(nd, Context):
            self.flush()
            self.uses.update(("push_sink", "pop_sink", "context"))
            self.w("push_sink()", nd.line)
            self.emit_children(nd.body)
            self.flush()
            self.w("__pcl_ctx = pop_sink()", nd.line)
            self.w("context(__pcl_ctx)", nd.line)
        elif isinstance(nd, Note):
            # 注记：body 为完整模板体——push_sink 渲染后 pop_sink 取文本，
            # 经 note() 下发（独立→输出文档；嵌入→会话 custom 条目）
            self.flush()
            self.uses.update(("push_sink", "pop_sink", "note"))
            self.w("push_sink()", nd.line)
            self.emit_children(nd.body)
            self.flush()
            self.w("__pcl_note = pop_sink()", nd.line)
            self.w("note(__pcl_note)", nd.line)
        elif isinstance(nd, Interp):
            self.emit_interp(nd)
        elif isinstance(nd, If):
            self.emit_if(nd)
        elif isinstance(nd, While):
            self.flush()
            self.w(f"while {nd.test}:", nd.line)
            self.block(nd.body, nd.line)
        elif isinstance(nd, For):
            self.flush()
            self.w(f"for {nd.header}:", nd.line)
            self.block(nd.body, nd.line)
        elif isinstance(nd, Break):
            self.flush()
            self.w("break", nd.line)
        elif isinstance(nd, Continue):
            self.flush()
            self.w("continue", nd.line)
        elif isinstance(nd, Return):
            self.flush()
            self.w(f"return ({nd.expr})" if nd.expr else "return", nd.line)
        elif isinstance(nd, Save):
            self.flush()
            self.uses.add("save")
            self.w(f"{nd.name} = save()", nd.line)
        elif isinstance(nd, Load):
            self.flush()
            self.uses.add("load")
            self.w(f"load({nd.name})", nd.line)
        elif isinstance(nd, NewCtx):
            self.flush()
            self.uses.add("new_ctx")
            self.w("new_ctx()", nd.line)
        elif isinstance(nd, Pass):
            self.emit_pass(nd)
        elif isinstance(nd, Function):
            self.flush()
            self.w(f"def {nd.name}({nd.params}):", nd.line)
            self.block(nd.body, nd.line)
        else:  # pragma: no cover
            raise AssertionError(f"未知节点 {type(nd).__name__}")

    def block(self, body: list, line: int):
        self.indent += 1
        try:
            if body:
                self.emit_children(body)
            else:
                self.w("pass", line)
            self.flush()  # 合并不跨块边界：仍在块内缩进时冲刷
        finally:
            self.indent -= 1

    def emit_if(self, nd: If):
        self.flush()
        for idx, arm in enumerate(nd.arms):
            if idx == 0:
                self.w(f"if {arm.test}:", arm.line)
            elif arm.test is not None:
                self.w(f"elif {arm.test}:", arm.line)
            else:
                self.w("else:", arm.line)
            self.block(arm.body, arm.line)

    def emit_interp(self, nd: Interp):
        if nd.form == "{":
            # 发起型：构造即冲刷点；表达式语句独立 emit（行号 1:1、保序）
            self.flush()
            for st in nd.stmts:
                src = _stmt_src(nd.content, st)
                line = nd.line + st.lineno - 1
                if isinstance(st, ast.Expr):
                    self.uses.update(("emit", "text"))
                    self.w(f"emit(text({src}))", line)
                else:
                    self.w(src, line)
        else:
            # 合并型：表达式立即求值暂存并织入合并段，纯语句不打断
            for st in nd.stmts:
                src = _stmt_src(nd.content, st)
                line = nd.line + st.lineno - 1
                if isinstance(st, ast.Expr):
                    t = self.tmp()
                    self.uses.add("text")
                    self.w(f"{t} = text({src})", line)
                    self.append_ref(t, line)
                else:
                    self.w(src, line)

    def emit_pass(self, nd: Pass):
        self.flush()
        if nd.read is not None:
            self.uses.add("__pcl_freeze")
            self.w(f'__pcl_reads = {{"{nd.read}": __pcl_freeze({nd.read})}}',
                   nd.line)
        self.uses.add("push_sink")
        self.w("push_sink()", nd.line)
        self.emit_children(nd.body)
        tl = nd.term_line if nd.term_line is not None else nd.line
        self.flush()
        self.uses.update(("pop_sink", "submit", "emit"))
        self.w("__pcl_buf = pop_sink()", tl)
        call_args = ["__pcl_buf"]
        if nd.read is not None:
            call_args.append("reads=__pcl_reads")
        if nd.write is not None:
            call_args.append(f'writes=("{nd.write}",)')
        self.w(f"__pcl_r = submit({', '.join(call_args)})", tl)
        self.w("reply = __pcl_r.reply", tl)
        if nd.write is not None:
            self.w(f'if "{nd.write}" in __pcl_r.writes: '
                   f'{nd.write} = __pcl_r.writes["{nd.write}"]', tl)
        self.w('emit(reply + ("\\n" if __pcl_buf.endswith("\\n") else ""))', tl)


def _main_globals(nodes: list) -> set[str]:
    """main 的 global 声明并集：reply、:write 名、main 内一切绑定目标（§9.2）。

    prompt 已由序言单独声明、不参与并集；:function 体内绑定为其局部名、不计入。
    """
    names = {"reply"}

    def visit(nodes):
        for nd in nodes:
            if isinstance(nd, Interp):
                names.update(binding_names(nd.stmts, include_ann=False))
            elif isinstance(nd, If):
                for arm in nd.arms:
                    visit(arm.body)
            elif isinstance(nd, While):
                visit(nd.body)
            elif isinstance(nd, For):
                names.update(nd.target_names)
                visit(nd.body)
            elif isinstance(nd, Pass):
                if nd.write is not None:
                    names.add(nd.write)
                visit(nd.body)
            elif isinstance(nd, Save):
                names.add(nd.name)
            elif isinstance(nd, Function):
                pass
            # Text/Break/Continue/Return/Load/NewCtx：无绑定

    visit(nodes)
    return names


_RUNTIME_ORDER = ("emit", "text", "submit", "push_sink", "pop_sink",
                  "note", "context", "save", "load", "new_ctx", "__pcl_freeze")


def _is_load_item(nd) -> bool:
    return isinstance(nd, Function) or (isinstance(nd, Interp) and nd.promoted)


def generate(nodes: list, filename: str, *, version: str) -> GenResult:
    """顶层节点列表 → 生成 Python 源。"""
    # ---- 加载层（源序）：:function 定义 + 可提升顶层插值 ----
    load = _Emitter()
    for nd in nodes:
        if isinstance(nd, Function):
            load.w(f"def {nd.name}({nd.params}):", nd.line)
            load.indent += 1
            try:
                if nd.body:
                    load.emit_children(nd.body)
                else:
                    load.w("pass", nd.line)
                load.flush()
            finally:
                load.indent -= 1
        elif isinstance(nd, Interp) and nd.promoted:
            for st in nd.stmts:
                load.w(_stmt_src(nd.content, st), nd.line + st.lineno - 1)

    # ---- main 体（源序，跳过加载层项） ----
    body = _Emitter()
    body.indent = 1
    for nd in nodes:
        if _is_load_item(nd):
            continue
        body.emit_node(nd)
    body.flush()
    if not body.lines:
        body.w("pass", 1)

    main_nodes = [nd for nd in nodes if not _is_load_item(nd)]
    globals_ = _main_globals(main_nodes)
    uses = load.uses | body.uses

    # ---- 组装 ----
    out: list[str] = []
    tpls: list = []

    def raw(line: str):
        out.append(line)
        tpls.append(None)

    raw(f"# 由 pcl {version} 生成，源：{filename}。请勿手工编辑。")
    imports = [n for n in _RUNTIME_ORDER if n in uses]
    if imports:
        raw(f"from pcl.runtime import {', '.join(imports)}")
    if load.lines:
        raw("")
        out.extend(load.lines)
        tpls.extend(load.tpls)
    raw("")
    raw('def main(__pcl_prompt=""):')
    raw(f"{INDENT}global {', '.join(['prompt'] + sorted(globals_))}")
    raw(f"{INDENT}prompt = __pcl_prompt")
    out.extend(body.lines)
    tpls.extend(body.tpls)
    source = "\n".join(out) + "\n"

    stem = filename.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return GenResult(source, f"{stem}.pcl.py", uses, tpls)
