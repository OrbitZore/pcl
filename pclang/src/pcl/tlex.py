"""tlex — PCL 模板词法（RFC 0000 §4）。

职责：
- ``$$`` 转义（单遍成对消解）与裸糖 ``$prompt``（≡ ``$(prompt)``）；
- 构造识别：插值双形式 ``${}`` / ``$()``、指令 ``${:动词 …}``、注释 ``${:# …}``；
- 闭合 = 括号配平（基于 :mod:`tokenize` 增量扫描，字符串/注释感知；
  ``${}`` 按 ``}``、``$()`` 按 ``)`` 闭合）；
- 跨行构造：仅三引号字符串吞并换行时合法（指令一律单行）；
- 行首/行尾 ASCII 空白剥除（空格/制表符；``\\r`` 按行终止符处理）、
  独行消除（行内全部构造无输出则整行移除，RFC 0000 §4.4）；
- 注释整行消除（未独行 → C305）。

输出：Token 流（Text / Interp / Directive / Comment 已消除不输出）。
"""

from __future__ import annotations

import ast
import re
from bisect import bisect_right
from tokenize import NEWLINE, NL, OP, TokenError, generate_tokens

from .errors import PclCompileError

# ASCII 空白集（剥除用，RFC 0000 §4.4：仅空格与制表符）
STRIP_WS = " \t"

# 完整标识符（unicode 感知），用于裸糖 $prompt 的最长匹配
_IDENT_RE = re.compile(r"[^\W\d]\w*", re.UNICODE)
_DELIM_MARKER_RE = re.compile(r"(\w+)([#@])")

# 已知指令动词（§6）
VERBS = frozenset({
    "if", "elif", "else", "fi", "while", "for", "done",
    "break", "continue", "function", "endfunction", "return",
    "pass", "save", "load", "new",
})

# 简单语句白名单（复合语句 → C300，RFC 0000 §10）
_SIMPLE_STMTS = (
    ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Expr,
    ast.Import, ast.ImportFrom, ast.Delete,
    ast.Pass, ast.Break, ast.Continue, ast.Return,
    ast.Assert, ast.Raise, ast.Global, ast.Nonlocal,
)


class TextTok:
    """构造之外的文本（已按行剥除/消除）。"""

    __slots__ = ("text", "line", "col")

    def __init__(self, text: str, line: int, col: int):
        self.text = text
        self.line = line
        self.col = col


class InterpTok:
    """插值构造：form 为 "{"（${} 发起型）或 "("（$() 合并型）。"""

    __slots__ = ("form", "content", "stmts", "has_expr", "line", "col")

    def __init__(self, form: str, content: str, stmts: list, line: int, col: int):
        self.form = form
        self.content = content
        self.stmts = stmts
        self.has_expr = any(isinstance(st, ast.Expr) for st in stmts)
        self.line = line
        self.col = col

    @property
    def no_output(self) -> bool:
        """无输出构造：语句列表不含表达式语句（独行消除判定，§4.4）。"""
        return not self.has_expr


class DirTok:
    """指令构造：verb + 原样参数串。"""

    __slots__ = ("verb", "args", "line", "col")

    def __init__(self, verb: str, args: str, line: int, col: int):
        self.verb = verb
        self.args = args
        self.line = line
        self.col = col


class NoteTok:
    """注记模板 ``$(# … #)``：内容为**完整模板体**（递归 tokenize，支持
    ``${}``/``$()``/指令/裸糖）。渲染结果经 ``note()`` 下发——正向/独立
    运行进输出文档（保序）；嵌入运行经桥接层 ``note`` 命令由连接器以
    custom entry 附加进会话流；均不进 LLM 上下文。
    """

    __slots__ = ("tokens", "line", "col")

    def __init__(self, tokens: list, line: int, col: int):
        self.tokens = tokens   # 递归 tokenize 的子 token 流
        self.line = line
        self.col = col

    @property
    def no_output(self) -> bool:
        return False   # 注记产生输出——独行不消除


class ContextTok:
    """上下文注入 ``$(@ … @)``：完整模板体（递归 tokenize）。渲染结果作为
    独立用户消息注入 agent 会话——不触发 LLM 推理。"""
    __slots__ = ("tokens", "line", "col")
    def __init__(self, tokens, line, col):
        self.tokens = tokens
        self.line = line
        self.col = col
    @property
    def no_output(self):
        return True

class _ContextItem:
    __slots__ = ("tok",)
    def __init__(self, tok): self.tok = tok

class _NoteItem:
    __slots__ = ("tok",)

    def __init__(self, tok: NoteTok):
        self.tok = tok


class _CommentItem:
    """词法内部的注释行项（最终整行消除，不进 Token 流）。"""

    __slots__ = ("line", "col")

    def __init__(self, line: int, col: int):
        self.line = line
        self.col = col


class _TextItem:
    __slots__ = ("text", "line", "col")

    def __init__(self, text: str, line: int, col: int):
        self.text = text
        self.line = line
        self.col = col


class _InterpItem:
    __slots__ = ("tok",)

    def __init__(self, tok: InterpTok):
        self.tok = tok


class _DirItem:
    __slots__ = ("tok",)

    def __init__(self, tok: DirTok):
        self.tok = tok


def tokenize(source: str, filename: str) -> list:
    """词法主入口：模板源文本 → Token 列表。

    ``source`` 为已解码文本（UTF-8 BOM 由调用方剥除）。
    编译期错误（L100–L102、C300、C305、C310、P200）以 PclCompileError 抛出。
    """
    return _Scanner(source, filename).run()


def parse_interp_content(content: str, filename: str, line: int, col: int) -> list[ast.stmt]:
    """解析插值构造内容为简单语句列表。

    - Python 语法错误 → C310（行号映射回 `.pcl`）；
    - 复合语句 → C300。
    """
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError) as exc:
        lineno = getattr(exc, "lineno", None) or 1
        offset = getattr(exc, "offset", None) or 1
        raise PclCompileError(
            "C310", f"Python 语法错误：{getattr(exc, 'msg', exc)}",
            file=filename, line=line + lineno - 1, col=col + offset - 1,
        ) from None
    for st in tree.body:
        if not isinstance(st, _SIMPLE_STMTS):
            raise PclCompileError(
                "C300", f"插值构造不允许复合语句（{type(st).__name__}），控制流请用 :if/:fi 等指令对",
                file=filename, line=line, col=col,
            )
    return tree.body


class _Scanner:
    def __init__(self, source: str, filename: str):
        self.src = source
        self.file = filename
        self.n = len(source)
        # 物理行起始偏移表（按 \n 切分；\r 不预剥离——构造内容需逐字保留，§4.4）
        self.line_starts = [0]
        for m in re.finditer("\n", source):
            self.line_starts.append(m.end())
        self.items: list = []   # 当前逻辑行项
        self.tokens: list = []  # 输出 Token

    # ---- 位置换算 -------------------------------------------------------

    def rowcol(self, off: int) -> tuple[int, int]:
        """偏移 → (1-based 行, 0-based 列)。"""
        i = bisect_right(self.line_starts, off)
        return i, off - self.line_starts[i - 1]

    def _map_back(self, row: int, col: int, row0: int, col0: int) -> int:
        """tokenize 馈入坐标（row 相对构造起始行）→ 源偏移。"""
        if row <= 1:
            return self.line_starts[row0 - 1] + col0 + col
        return self.line_starts[row0 + row - 2] + col

    # ---- 主循环 ---------------------------------------------------------

    def run(self) -> list:
        src, n = self.src, self.n
        i = 0
        # 首行 #! 忽略（§4.1）
        if src.startswith("#!"):
            i = self.line_starts[1] if len(self.line_starts) > 1 else n
        while i < n:
            c = src[i]
            if c == "\n":
                self._finalize(has_nl=True, line=self.rowcol(i)[0])
                i += 1
                continue
            if c == "\r":
                nxt = src[i + 1] if i + 1 < n else ""
                # 紧邻 \n 的 \r、文件末尾孤立 \r → 行终止符一部分，剥离（§4.4）
                if nxt == "\n" or nxt == "":
                    i += 1
                    continue
                self._text("\r", i)  # 行中间孤立 \r 按内容原样
                i += 1
                continue
            if c == "$":
                nxt = src[i + 1] if i + 1 < n else ""
                if nxt == "$":            # $$ → 字面 $（单遍成对消解）
                    self._text("$", i)
                    i += 2
                    continue
                if nxt and nxt in "{(":
                    i = self._construct(i)
                    continue
                m = _IDENT_RE.match(src, i + 1)
                if m and m.group() == "prompt":  # 裸糖 $prompt ≡ $(prompt)
                    row, col = self.rowcol(i)
                    stmts = parse_interp_content("prompt", self.file, row, col + 1)
                    self.items.append(_InterpItem(InterpTok("(", "prompt", stmts, row, col + 1)))
                    i = m.end()
                    continue
                self._text("$", i)  # 其余 $ 为普通字符
                i += 1
                continue
            # 普通文本段：扫到下一个特殊字符
            j = i
            while j < n and src[j] not in "$\n\r":
                j += 1
            self._text(src[i:j], i)
            i = j
        self._finalize(has_nl=False, line=self.rowcol(max(i - 1, 0))[0] if n else 1)
        return self.tokens

    def _text(self, s: str, off: int):
        row, col = self.rowcol(off)
        last = self.items[-1] if self.items else None
        if isinstance(last, _TextItem):
            last.text += s
        else:
            self.items.append(_TextItem(s, row, col))

    # ---- 构造识别 -------------------------------------------------------

    def _construct(self, i: int) -> int:
        """i 位于 '$'；返回构造结束偏移（闭界定界符之后）。"""
        src = self.src
        start_off = i
        content_off = i + 2
        row, col = self.rowcol(start_off)

        if content_off < self.n and src[content_off] == ":":
            if content_off + 1 < self.n and src[content_off + 1] == "#":
                return self._comment(start_off)
            return self._directive(start_off, content_off, row, col)
        if src[i + 1] == "{":
            if content_off < self.n and src[content_off] == "#":
                # 注释简写 ${# …（≡ ${:# …，行界定）
                return self._comment(start_off)
        elif src[i + 1] == "(":
            if content_off < self.n and src[content_off] == "#":
                return self._note(start_off, content_off, row, col)
            if content_off < self.n and src[content_off] == "@":
                return self._context(start_off, content_off, row, col)
            # 扩展定界符 $(<delim># … <delim>#) / $(<delim>@ … <delim>@)
            # —— 同 C++ raw string，防止内容中出现 #) 或 @)
            m = _DELIM_MARKER_RE.match(src, content_off, content_off + 256)
            if m and m.group(1):
                delim, marker = m.group(1), m.group(2)
                closer_str = marker + delim + ")"   # 严格对称：<delim># … #<delim>) / <delim>@ … @<delim>)
                end = src.find(closer_str, m.end())
                if end != -1:
                    body = src[m.end():end].strip("\n")
                    try:
                        sub = tokenize(body, self.file)
                    except PclCompileError:
                        raise
                    if marker == "#":
                        self.items.append(_NoteItem(NoteTok(sub, row, col + 1)))
                    else:
                        self.items.append(_ContextItem(ContextTok(sub, row, col + 1)))
                    return end + len(closer_str)
        closer = "}" if src[i + 1] == "{" else ")"
        form = "{" if closer == "}" else "("
        closer_off, saw_nl = self._find_closer(content_off, closer)
        end_row = self.rowcol(closer_off)[0]
        if end_row != row and saw_nl:
            raise PclCompileError(
                "L100", "构造未闭合（仅三引号字符串内的换行允许构造跨行）",
                file=self.file, line=row, col=col + 1,
            )
        content = src[content_off:closer_off].strip(" \t\n\r")
        stmts = parse_interp_content(content, self.file, row, col + 1)
        self.items.append(_InterpItem(InterpTok(form, content, stmts, row, col + 1)))
        return closer_off + 1

    def _context(self, start_off: int, at_off: int, row: int, col: int) -> int:
        close = self.src.find("@)", at_off + 1)
        if close == -1:
            raise PclCompileError("L100", "上下文注入 $(@ … @) 未闭合（缺少 @)）",
                                file=self.file, line=row, col=col + 1)
        body = self.src[at_off + 1:close].strip("\n")
        try:
            sub_tokens = tokenize(body, self.file)
        except PclCompileError:
            raise
        self.items.append(_ContextItem(ContextTok(sub_tokens, row, col + 1)))
        return close + 2

    def _note(self, start_off: int, hash_off: int, row: int, col: int) -> int:
        """``$(# … #)``：内容为完整模板体（可跨行），闭合符为字面 ``#)``。

        内容递归调用 tokenize() 解析为子 token 流——支持 ${}/$()/指令/
        裸糖/嵌套注记。"""
        close = self.src.find("#)", hash_off + 1)
        if close == -1:
            raise PclCompileError(
                "L100", "注记 $(# … #) 未闭合（缺少 #)）",
                file=self.file, line=row, col=col + 1,
            )
        body = self.src[hash_off + 1:close].strip("\n")
        # 递归 tokenize：内容走完整模板管线（含行消除等）
        try:
            sub_tokens = tokenize(body, self.file)
        except PclCompileError:
            raise   # 子模板错误原样传播（行号已映射到子模板；可后续做行号偏移）
        self.items.append(_NoteItem(NoteTok(sub_tokens, row, col + 1)))
        return close + 2

    def _comment(self, start_off: int) -> int:
        """${:# …}：行界定，# 起至行尾整体丢弃（§4.5）。"""
        row, col = self.rowcol(start_off)
        self.items.append(_CommentItem(row, col))
        eol = self.src.find("\n", start_off)
        return self.n if eol == -1 else eol

    def _directive(self, start_off: int, content_off: int, row: int, col: int) -> int:
        import re as _re
        m = _re.compile("[A-Za-z]+").match(self.src, content_off + 1)
        if not m:
            snippet = self.src[content_off:min(content_off + 12, self.n)]
            raise PclCompileError(
                "P200", f"无法识别的指令：{snippet!r}",
                file=self.file, line=row, col=col + 1,
            )
        verb = m.group()
        if verb not in VERBS:
            raise PclCompileError(
                "P200", f"未知指令 :{verb}",
                file=self.file, line=row, col=col + 1,
            )
        closer_off, saw_nl = self._find_closer(content_off, "}")
        end_row = self.rowcol(closer_off)[0]
        if end_row != row or saw_nl:
            # 指令不享三引号跨行豁免（§4.2）
            raise PclCompileError(
                "L100", f"指令 :{verb} 未在单行内闭合",
                file=self.file, line=row, col=col + 1,
            )
        args = self.src[m.end():closer_off].strip(STRIP_WS)
        self.items.append(_DirItem(DirTok(verb, args, row, col + 1)))
        return closer_off + 1

    def _find_closer(self, off: int, closer: str) -> tuple[int, bool]:
        """自 off（构造内容起点）扫描闭合定界符。

        返回 (闭合符后偏移, 是否出现代码换行 NL/NEWLINE)。
        基于 tokenize：跳过字符串字面量与 ``#`` 注释、统计括号深度；
        ``closer`` 为深度 0 处首个对应定界符。
        """
        src, n = self.src, self.n
        row0, col0 = self.rowcol(off)
        cur = off

        def readline():
            nonlocal cur
            if cur >= n:
                return ""
            e = src.find("\n", cur)
            if e == -1:
                s = src[cur:]
                cur = n
                return s
            s = src[cur:e] + "\n"
            cur = e + 1
            return s

        depth = 0
        saw_nl = False
        try:
            for tok in generate_tokens(readline):
                if tok.type in (NL, NEWLINE):
                    saw_nl = True
                elif tok.type == OP:
                    s = tok.string
                    if s in "([{":
                        depth += 1
                    elif s in ")]}":
                        if depth > 0:
                            depth -= 1
                        elif s == closer:
                            # 闭合符为单字符：起始偏移即内容终点（tok.start）
                            return (self._map_back(tok.start[0], tok.start[1],
                                                   row0, col0), saw_nl)
                        # 深度 0 的另一种闭合符：交由 Python 语法检查报错（C310）
        except (TokenError, IndentationError, SyntaxError, ValueError,
                RecursionError) as exc:
            # ValueError 含 UnicodeDecodeError（C tokenizer 对病态输入的
            # 再解码失败——模糊测试实测）；RecursionError 为嵌套过深兜底
            raise PclCompileError(
                "L101", f"词法扫描失败：{type(exc).__name__}: {exc}",
                file=self.file, line=self.rowcol(off)[0], col=self.rowcol(off)[1] + 1,
            ) from None
        raise PclCompileError(
            "L100", "构造未闭合",
            file=self.file, line=self.rowcol(off)[0], col=self.rowcol(off)[1] + 1,
        )

    # ---- 逻辑行终结：剥除与独行消除（§4.4） ---------------------------

    def _finalize(self, has_nl: bool, line: int):
        items, self.items = self.items, []
        if not items:
            if has_nl:
                self.tokens.append(TextTok("\n", line, 0))
            return

        # 行首/行尾空白剥除（仅文本段；构造内容不动）——先剥再查 C305
        if isinstance(items[0], _TextItem):
            items[0].text = items[0].text.lstrip(STRIP_WS)
            if not items[0].text:
                items.pop(0)
        if items and isinstance(items[-1], _TextItem):
            items[-1].text = items[-1].text.rstrip(STRIP_WS)
            if not items[-1].text:
                items.pop()

        # C305：注释必须独占一行（空白已剥除；行界定注释吞行尾文本不违例）
        if any(isinstance(it, _CommentItem) for it in items):
            if len(items) != 1:
                first = items[0]
                ln = first.tok.line if isinstance(first, (_InterpItem, _DirItem)) else first.line
                col = first.tok.col if isinstance(first, (_InterpItem, _DirItem)) else first.col
                raise PclCompileError(
                    "C305", "注释 ${:# …}/${# …} 必须独占一行",
                    file=self.file, line=ln, col=col + 1,
                )
            return  # 独行注释：整行消除

        texts = [it for it in items if isinstance(it, _TextItem)]
        constructs = [it for it in items
                      if isinstance(it, (_InterpItem, _DirItem, _NoteItem, _ContextItem))]

        if not constructs:
            text = "".join(it.text for it in texts)
            self.tokens.append(TextTok(text + ("\n" if has_nl else ""), line, 0))
            return

        if texts or not all(
            it.tok.no_output if isinstance(it, (_InterpItem, _NoteItem, _ContextItem)) else True
            for it in constructs
        ):
            # 含文本或含输出构造：整行保留
            for it in items:
                if isinstance(it, _TextItem):
                    if it.text:
                        self.tokens.append(TextTok(it.text, it.line, it.col))
                else:
                    self.tokens.append(it.tok)
            if has_nl:
                self.tokens.append(TextTok("\n", line, 0))
        else:
            # 独行消除：全部构造无输出 → 移除文本与换行，仅保留构造本身
            for it in constructs:
                self.tokens.append(it.tok)
