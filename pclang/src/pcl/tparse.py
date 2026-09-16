"""tparse — PCL AST（dataclass）、块配对与静态检查（DESIGN §5.1，DSL §6/§9.2）。

Token 流（tlex）→ 嵌套节点树：
- Text / Interp（双形式，含原样语句列表）
- If（多臂）/ While / For / Break / Continue / Return
- Function（params 原样透传）/ Pass（read/write/body）
- Save / Load / NewCtx

静态检查：
- P200 指令参数（:read/:write/:save/:load/:function 实参须单个标识符等）
- P201 位置违例与块配对（break/continue 循环外、return 函数外、function 非顶层、
  elif/else 错位、fi/done/endfunction 配对）
- P202 pass 体为空；P203 pass 体内插值含 break/continue/return
- C300 保留名绑定（8 个运行时名与 __pcl_ 前缀；:function 名 main/prompt/reply）、
  非提升位置 ``import *``
- 加载层提升判定（DSL §9.2：整体为 import / 字面量赋值）
"""

from __future__ import annotations

import ast
import keyword
import re
from dataclasses import dataclass, field

from .errors import PclCompileError
from .tlex import DirTok, InterpTok, NoteTok, TextTok

# 运行时保留名（DSL §9.2：9 名一律保留，无论是否用到；note 为 v0.2 新增）
RUNTIME_RESERVED = frozenset({
    "emit", "text", "submit", "save", "load",
    "new_ctx", "push_sink", "pop_sink", "note",
})
# :function 名专用保留
FUNCTION_RESERVED = frozenset({"main", "prompt", "reply"})

_FUNC_RE = re.compile(r"([^\W\d]\w*)\s*(\((.*)\))?\s*$", re.UNICODE)


# ---- AST 节点 -----------------------------------------------------------

@dataclass
class Node:
    line: int
    col: int


@dataclass
class Text(Node):
    text: str


@dataclass
class Note(Node):
    """注记 ``$(# … #)``：body 为完整模板体（支持插值/指令/嵌套）。
    渲染结果经 note() 下发——独立运行进输出文档；嵌入进会话 custom 条目；
    均不进 LLM 上下文。"""

    body: list = field(default_factory=list)


@dataclass
class Interp(Node):
    form: str            # "{" 发起型 / "(" 合并型
    content: str         # 原样语句列表源码
    stmts: list          # ast.stmt 列表（简单语句）
    has_expr: bool = False
    has_star: bool = False
    promotable: bool = False
    promoted: bool = False  # 顶层且整体为 import/字面量赋值 → 提升至加载层

    def __post_init__(self):
        self.has_expr = any(isinstance(st, ast.Expr) for st in self.stmts)
        self.has_star = any(
            isinstance(st, ast.ImportFrom)
            and any(a.name == "*" for a in st.names)
            for st in self.stmts
        )


@dataclass
class IfArm:
    test: str | None     # None = else 臂
    body: list
    line: int
    col: int


@dataclass
class If(Node):
    arms: list = field(default_factory=list)


@dataclass
class While(Node):
    test: str = ""
    body: list = field(default_factory=list)


@dataclass
class For(Node):
    header: str = ""     # 原样 "X in EXPR"
    body: list = field(default_factory=list)
    target_names: list = field(default_factory=list)


@dataclass
class Break(Node):
    pass


@dataclass
class Continue(Node):
    pass


@dataclass
class Return(Node):
    expr: str | None = None


@dataclass
class Function(Node):
    name: str = ""
    params: str = 'prompt=""'
    body: list = field(default_factory=list)
    param_names: list = field(default_factory=list)


@dataclass
class Pass(Node):
    read: str | None = None
    write: str | None = None
    body: list = field(default_factory=list)
    term_line: int | None = None   # 终止指令行；EOF 终止为 None（发射时回退自身行）


@dataclass
class Save(Node):
    name: str = ""


@dataclass
class Load(Node):
    name: str = ""


@dataclass
class NewCtx(Node):
    pass


# ---- 绑定目标分析 ---------------------------------------------------------

def _names_in_target(target) -> list[str]:
    """赋值目标（Name/Tuple/List/Starred 递归）→ 名字列表。"""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        out = []
        for el in target.elts:
            out.extend(_names_in_target(el))
        return out
    if isinstance(target, ast.Starred):
        return _names_in_target(target.value)
    return []


def binding_names(stmts, *, include_ann: bool = True) -> set[str]:
    """语句列表中的绑定目标名（含 walrus 与推导式内 NamedExpr；不含推导式迭代变量）。

    覆盖赋值/增强赋值/import 绑定与 del 目标；``include_ann`` 控制是否计入
    注解赋值目标（global 并集不可含它——Python 禁止 ``global W`` 与
    ``W: ann = v`` 同现，故仅保留名检查需要计入）。
    """
    names: set[str] = set()
    for st in ast.walk(ast.Module(body=list(stmts), type_ignores=[])):
        if isinstance(st, ast.NamedExpr):
            names.add(st.target.id)
        elif isinstance(st, ast.Assign):
            for t in st.targets:
                names.update(_names_in_target(t))
        elif isinstance(st, ast.AugAssign):
            names.update(_names_in_target(st.target))
        elif isinstance(st, ast.AnnAssign) and include_ann:
            names.update(_names_in_target(st.target))
        elif isinstance(st, ast.Delete):
            for t in st.targets:
                names.update(_names_in_target(t))
        elif isinstance(st, ast.Import):
            for a in st.names:
                names.add(a.asname or a.name.split(".")[0])
        elif isinstance(st, ast.ImportFrom):
            for a in st.names:
                names.add(a.asname or a.name)
    return names


def _is_literal_value(v) -> bool:
    """字面量 / 纯字面量容器 / 数值字面量的一元 ±~（DSL §9.2）。"""
    if isinstance(v, ast.Constant):
        return True
    if isinstance(v, (ast.Tuple, ast.List, ast.Set)):
        return all(_is_literal_value(e) for e in v.elts)
    if isinstance(v, ast.UnaryOp) and isinstance(v.op, (ast.USub, ast.UAdd, ast.Invert)):
        return isinstance(v.operand, ast.Constant) and isinstance(
            v.operand.value, (int, float, complex))
    return False


def _is_promotable_stmts(stmts) -> bool:
    """语句列表整体为 import / 字面量赋值（可提升至加载层，DSL §9.2）。"""
    for st in stmts:
        if isinstance(st, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(st, ast.Assign) and _is_literal_value(st.value):
            bad = any(
                isinstance(t, (ast.Attribute, ast.Subscript)) or not _names_in_target(t)
                for t in st.targets
            )
            if not bad:
                continue
        return False
    return True


def _is_ident(s: str) -> bool:
    return bool(s) and s.isidentifier() and not keyword.iskeyword(s)


# ---- 解析器 ---------------------------------------------------------------

class _Parser:
    def __init__(self, tokens: list, filename: str):
        self.toks = tokens
        self.file = filename

    def err(self, code: str, msg: str, line: int, col: int):
        raise PclCompileError(code, msg, file=self.file, line=line, col=col)

    def parse(self) -> list:
        body, i = self.parse_seq(0, top=True, in_function=False, in_loop=False)
        if i != len(self.toks):
            t = self.toks[i]
            self.err("P201", f"指令 :{t.verb} 出现在不合法的位置", t.line, t.col)
        return body

    def parse_seq(self, i, *, top, in_function, in_loop) -> tuple[list, int]:
        """解析构造序列，直至终止指令（不消费）或 EOF。"""
        nodes = []
        while i < len(self.toks):
            t = self.toks[i]
            if isinstance(t, TextTok):
                nodes.append(Text(t.line, t.col, t.text))
                i += 1
                continue
            if isinstance(t, NoteTok):
                sub = _Parser(t.tokens, self.file if hasattr(self, "file") else "?")
                body, j = sub.parse_seq(0, top=False, in_function=False,
                                        in_loop=False)
                nodes.append(Note(t.line, t.col, body))
                i += 1
                continue
            if isinstance(t, InterpTok):
                nodes.append(self.check_interp(
                    Interp(t.line, t.col, t.form, t.content, t.stmts), top=top))
                i += 1
                continue
            if t.verb in ("fi", "done", "endfunction", "elif", "else"):
                return nodes, i   # 交由上层块配对；顶层残留由 parse() 报 P201
            i = self.parse_directive(t, i, nodes, top=top,
                                     in_function=in_function, in_loop=in_loop)
        return nodes, i

    def check_interp(self, node: Interp, *, top: bool) -> Interp:
        node.promotable = _is_promotable_stmts(node.stmts)
        node.promoted = top and node.promotable
        if node.has_star and not node.promoted:
            self.err("C300", "`import *` 仅允许在可提升的顶层插值构造中",
                     node.line, node.col)
        return node

    def parse_directive(self, t: DirTok, i, nodes, *, top, in_function, in_loop) -> int:
        v, args = t.verb, t.args
        E = self.err

        def need_args():
            if not args:
                E("P200", f"指令 :{v} 缺少参数", t.line, t.col)

        def no_args():
            if args:
                E("P200", f"指令 :{v} 不接受参数", t.line, t.col)

        if v == "if":
            need_args()
            node = If(t.line, t.col)
            arm_test = args
            opener = t
            i += 1

            def no_args_on(nt: DirTok, verb: str):
                if nt.args:
                    E("P200", f"指令 :{verb} 不接受参数", nt.line, nt.col)

            while True:
                body, i = self.parse_seq(i, top=False, in_function=in_function,
                                         in_loop=in_loop)
                node.arms.append(IfArm(arm_test, body, opener.line, opener.col))
                if i >= len(self.toks):
                    E("P201", ":if 块未闭合（缺少 :fi）", opener.line, opener.col)
                nt = self.toks[i]
                if nt.verb == "elif":
                    if arm_test is None:
                        E("P201", ":else 后不允许再接 :elif", nt.line, nt.col)
                    if not nt.args:
                        E("P200", "指令 :elif 缺少参数", nt.line, nt.col)
                    arm_test, opener = nt.args, nt
                    i += 1
                elif nt.verb == "else":
                    if arm_test is None:
                        E("P201", ":else 后不允许再接 :else", nt.line, nt.col)
                    no_args_on(nt, "else")
                    arm_test, opener = None, nt
                    i += 1
                elif nt.verb == "fi":
                    if nt.args:
                        E("P200", "指令 :fi 不接受参数", nt.line, nt.col)
                    i += 1
                    break
                else:
                    E("P201", f":if 块期望 :elif/:else/:fi，得到 :{nt.verb}",
                      nt.line, nt.col)
            nodes.append(node)
            return i

        if v == "while":
            need_args()
            body, i = self.parse_seq(i + 1, top=False, in_function=in_function,
                                     in_loop=True)
            self.expect(i, "done", t)
            nodes.append(While(t.line, t.col, args, body))
            return i + 1

        if v == "for":
            need_args()
            names = self.for_target_names(args, t)
            body, i = self.parse_seq(i + 1, top=False, in_function=in_function,
                                     in_loop=True)
            self.expect(i, "done", t)
            nodes.append(For(t.line, t.col, args, body, names))
            return i + 1

        if v == "break":
            if not in_loop:
                E("P201", ":break 出现在循环体外", t.line, t.col)
            no_args()
            nodes.append(Break(t.line, t.col))
            return i + 1

        if v == "continue":
            if not in_loop:
                E("P201", ":continue 出现在循环体外", t.line, t.col)
            no_args()
            nodes.append(Continue(t.line, t.col))
            return i + 1

        if v == "function":
            if not top:
                E("P201", ":function 只能出现在顶层", t.line, t.col)
            name, params, pnames = self.parse_function(args, t)
            body, i = self.parse_seq(i + 1, top=False, in_function=True, in_loop=False)
            self.expect(i, "endfunction", t)
            nodes.append(Function(t.line, t.col, name, params, body, pnames))
            return i + 1

        if v == "return":
            if not in_function:
                E("P201", ":return 出现在函数体外", t.line, t.col)
            nodes.append(Return(t.line, t.col, args or None))
            return i + 1

        if v == "pass":
            read, write = self.parse_pass_args(args, t)
            body, i = self.parse_pass_body(i + 1)
            if not body:
                E("P202", "pass 体为空", t.line, t.col)
            term_line = self.toks[i].line if i < len(self.toks) else None
            nodes.append(Pass(t.line, t.col, read, write, body, term_line=term_line))
            return i

        if v == "save":
            if not _is_ident(args):
                E("P200", "指令 :save 实参须为单个 Python 名字", t.line, t.col)
            nodes.append(Save(t.line, t.col, args))
            return i + 1

        if v == "load":
            if not _is_ident(args):
                E("P200", "指令 :load 实参须为单个 Python 名字", t.line, t.col)
            nodes.append(Load(t.line, t.col, args))
            return i + 1

        if v == "new":
            no_args()
            nodes.append(NewCtx(t.line, t.col))
            return i + 1

        E("P200", f"未知指令 :{v}", t.line, t.col)

    def expect(self, i, verb, opener: DirTok):
        if i >= len(self.toks):
            self.err("P201", f":{opener.verb} 块未闭合（缺少 :{verb}）",
                     opener.line, opener.col)
        t = self.toks[i]
        if t.verb != verb:
            self.err("P201", f":{opener.verb} 块期望 :{verb}，得到 :{t.verb}",
                     t.line, t.col)
        if t.args:
            self.err("P200", f"指令 :{verb} 不接受参数", t.line, t.col)

    def for_target_names(self, header: str, t: DirTok) -> list[str]:
        try:
            tree = ast.parse(f"for {header}: pass")
            st = tree.body[0]
        except (SyntaxError, ValueError, IndexError):
            self.err("P200", "指令 :for 参数须形如 “X in EXPR”", t.line, t.col)
        return _names_in_target(st.target)

    def parse_function(self, args: str, t: DirTok):
        m = _FUNC_RE.match(args)
        if not m or not m.group(1):
            self.err("P200", "指令 :function 参数须形如 “NAME(参数列表)” 或 “NAME”",
                     t.line, t.col)
        name = m.group(1)
        if keyword.iskeyword(name):
            self.err("P200", f":function 名 {name!r} 是 Python 关键字", t.line, t.col)
        if name in FUNCTION_RESERVED:
            self.err("C300", f":function 名 {name!r} 为保留名", t.line, t.col)
        params = m.group(3) if m.group(2) is not None else 'prompt=""'
        pnames: list[str] = []
        try:
            ftree = ast.parse(f"def _({params or ''}): pass")
            fargs = ftree.body[0].args
            for a in (*fargs.posonlyargs, *fargs.args, *fargs.kwonlyargs):
                pnames.append(a.arg)
            if fargs.vararg:
                pnames.append(fargs.vararg.arg)
            if fargs.kwarg:
                pnames.append(fargs.kwarg.arg)
        except (SyntaxError, ValueError, IndexError):
            self.err("P200", f":function 参数列表无效：{params!r}", t.line, t.col)
        return name, params, pnames

    def parse_pass_args(self, args: str, t: DirTok):
        read = write = None
        toks = args.split()
        idx = 0
        while idx < len(toks):
            flag = toks[idx]
            if flag not in (":read", ":write"):
                self.err("P200", f"指令 :pass 参数无效：{flag!r}", t.line, t.col)
            if idx + 1 >= len(toks) or not _is_ident(toks[idx + 1]):
                self.err("P200", f":pass {flag} 实参须为单个 Python 标识符",
                         t.line, t.col)
            name = toks[idx + 1]
            if flag == ":read":
                if read is not None:
                    self.err("P200", ":read 至多出现一次", t.line, t.col)
                read = name
            else:
                if write is not None:
                    self.err("P200", ":write 至多出现一次", t.line, t.col)
                write = name
            idx += 2
        return read, write

    def parse_pass_body(self, i) -> tuple[list, int]:
        """pass 体 = 输出构造序列，遇下一个指令（或 EOF）终止（§7）。"""
        body = []
        while i < len(self.toks):
            t = self.toks[i]
            if isinstance(t, TextTok):
                body.append(Text(t.line, t.col, t.text))
                i += 1
                continue
            if isinstance(t, InterpTok):
                node = self.check_interp(
                    Interp(t.line, t.col, t.form, t.content, t.stmts), top=False)
                if any(isinstance(st, (ast.Break, ast.Continue, ast.Return))
                       for st in node.stmts):
                    self.err("P203",
                             "pass 体内插值不允许 break/continue/return"
                             "（会跳过自动提交点，泄漏缓冲）", t.line, t.col)
                body.append(node)
                i += 1
                continue
            if isinstance(t, NoteTok):
                body.append(Note(t.line, t.col, t.text))
                i += 1
                continue
            break
        return body, i


def parse(tokens: list, filename: str) -> list:
    """Token 流 → 顶层节点列表（含静态检查）。"""
    p = _Parser(tokens, filename)
    body = p.parse()
    _check_reserved(body, filename)
    return body


def _check_reserved(nodes: list, filename: str):
    """运行时保留名 / __pcl_ 前缀作为绑定目标 → C300（含 :function 名与形参）。"""

    def bad(name):
        return name in RUNTIME_RESERVED or name.startswith("__pcl_")

    def fail(name, line, col, what):
        raise PclCompileError(
            "C300", f"{what} {name!r} 与运行时保留名/保留前缀冲突",
            file=filename, line=line, col=col)

    def walk(nodes):
        for nd in nodes:
            if isinstance(nd, Interp):
                for nm in binding_names(nd.stmts):
                    if bad(nm):
                        fail(nm, nd.line, nd.col, "绑定目标")
            elif isinstance(nd, If):
                for arm in nd.arms:
                    walk(arm.body)
            elif isinstance(nd, While):
                walk(nd.body)
            elif isinstance(nd, For):
                for nm in nd.target_names:
                    if bad(nm):
                        fail(nm, nd.line, nd.col, ":for 循环变量")
                walk(nd.body)
            elif isinstance(nd, Function):
                if bad(nd.name):
                    fail(nd.name, nd.line, nd.col, ":function 名")
                for nm in nd.param_names:
                    if bad(nm):
                        fail(nm, nd.line, nd.col, ":function 形参")
                walk(nd.body)
            elif isinstance(nd, Pass):
                if nd.write is not None and bad(nd.write):
                    fail(nd.write, nd.line, nd.col, ":write 名")
                walk(nd.body)
            elif isinstance(nd, Save):
                if bad(nd.name):
                    fail(nd.name, nd.line, nd.col, ":save 名")
            # Text/Break/Continue/Return/Load/NewCtx：无绑定

    walk(nodes)
