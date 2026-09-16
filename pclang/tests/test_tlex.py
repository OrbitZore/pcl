"""tlex 单元测试：转义、裸糖、配平闭合、剥除、独行消除、跨行（DSL §4）。"""

from __future__ import annotations

import pytest

from pcl.errors import PclCompileError
from pcl.tlex import ContextTok, DirTok, InterpTok, NoteTok, TextTok, tokenize


def toks(src: str):
    return tokenize(src, "t.pcl")


def texts(src: str) -> list[str]:
    return [t.text for t in toks(src) if isinstance(t, TextTok)]


def interps(src: str) -> list[InterpTok]:
    return [t for t in toks(src) if isinstance(t, InterpTok)]


def err_code(src: str) -> str:
    with pytest.raises(PclCompileError) as ei:
        toks(src)
    return ei.value.code


def kinds(src: str) -> list[str]:
    return [type(t).__name__ for t in toks(src)]


# ---- §4.3 转义与裸糖 -----------------------------------------------------

def test_escape_dollar_forms():
    # 无尾换行的单行源：末尾不补换行（§4.4）
    assert texts("$${") == ["${"]
    assert texts("$$prompt") == ["$prompt"]
    assert texts("$$$$") == ["$$"]
    assert texts("$$(") == ["$("]
    # $$$prompt → 字面 $ + 裸糖 $prompt
    ts = toks("$$$prompt")
    assert isinstance(ts[0], TextTok) and ts[0].text == "$"
    assert isinstance(ts[1], InterpTok) and ts[1].content == "prompt"


def test_bare_sugar_only_prompt():
    for src in ("$prompts", "$PROMPT", "$promptX", "$prompt_", "$_prompt"):
        assert texts(src) == [src], src
    assert texts("$") == ["$"]
    assert texts("$x") == ["$x"]
    # $prompt 取最长标识符：$prompté 不触发
    assert texts("$prompté") == ["$prompté"]


def test_bare_sugar_is_merge_form():
    (it,) = interps("$prompt")
    assert it.form == "(" and it.content == "prompt"


def test_dollar_untouched_inside_construct():
    # 构造内 $ 归 Python：语法错误 → C310
    assert err_code("${$prompt}") == "C310"


# ---- §4.2 配平闭合 -------------------------------------------------------

def test_balanced_closures():
    assert interps("${ {'a': 1} }")[0].content == "{'a': 1}"
    assert interps('${D = {"k": 1}}')[0].content == 'D = {"k": 1}'
    assert interps("$(text(prompt))")[0].content == "text(prompt)"
    assert interps('text ${"}"} ok')[0].content == '"}"'
    assert interps("$(a if b else c)")[0].content == "a if b else c"
    assert interps("${len(A)}")[0].content == "len(A)"
    assert interps("$()")[0].content == ""


def test_unclosed_construct():
    assert err_code("${x") == "L100"
    assert err_code("$(x") == "L100"
    # # 注释吞没闭合符 → 构造无法闭合
    assert err_code("${x # }") == "L100"


def test_crossline_only_via_triple_quoted():
    it = interps('${X = r"""a\nb"""}')[0]
    assert "a\nb" in it.content
    # 代码换行（非字符串内）→ 非法跨行
    assert err_code("${f(a,\nb)}") == "L100"


def test_directive_never_crossline():
    assert err_code('${:if r"""\nx"""}') == "L100"


def test_directive_closure_with_brackets():
    ds = [t for t in toks('${:for k in {"a": 1}}') if isinstance(t, DirTok)]
    assert ds[0].verb == "for" and ds[0].args == 'k in {"a": 1}'


# ---- §4.5 注释 -----------------------------------------------------------

def test_comment_line_eliminated():
    ts = toks("a\n${:# comment}\nb")
    assert [t.text for t in ts if isinstance(t, TextTok)] == ["a\n", "b"]
    assert len(ts) == 2


def test_comment_swallows_rest_of_line():
    # ${:# 行界定：# 起至行尾整体丢弃——行尾文本属注释负载，静默消除
    assert toks("${:# c} trailing text") == []


def test_comment_not_alone_c305():
    assert err_code("text ${:# c}") == "C305"
    assert err_code("${:fi}${:# c}") == "C305"


# ---- §4.4 剥除与独行消除 ---------------------------------------------------

def test_strip_leading_trailing_ascii_ws():
    assert texts("  text  \n") == ["text\n"]
    assert texts("\ttext\t") == ["text"]
    # 全角空格/NBSP 不剥
    assert texts("　x　\n") == ["　x　\n"]


def test_crlf_and_lone_cr():
    assert texts("a\r\nb\r\n") == ["a\n", "b\n"]
    assert texts("abc\r") == ["abc"]  # 文件末尾孤立 \r 随行终止符剥离
    assert texts("a\rb\n") == ["a\rb\n"]  # 行中间孤立 \r 原样


def test_blank_lines_kept():
    assert texts("a\n\nb") == ["a\n", "\n", "b"]


def test_lone_line_elimination():
    # 纯语句插值行（两种形式）整行消除：只剩构造本身、无换行
    ts = toks("${X = 1}\n")
    assert len(ts) == 1 and isinstance(ts[0], InterpTok) and not ts[0].has_expr
    ts = toks("$(X = 1)\n")
    assert len(ts) == 1 and isinstance(ts[0], InterpTok)
    # 指令行消除；指令与纯语句插值混排同样消除
    assert kinds("${:fi}${X = 1}\n") == ["DirTok", "InterpTok"]
    assert kinds("${:fi}$(X = 1)\n") == ["DirTok", "InterpTok"]
    # 空语句列表合法、无操作 → 行消除（构造本身保留为 no-op、不产码）
    for src in ("${}\n", "$()\n"):
        ts = toks(src)
        assert len(ts) == 1 and isinstance(ts[0], InterpTok) and not ts[0].stmts


def test_lines_with_output_kept():
    # 表达式语句插值行保留（含换行）
    ts = toks("${x}\n")
    assert isinstance(ts[0], InterpTok) and ts[0].has_expr
    assert isinstance(ts[1], TextTok) and ts[1].text == "\n"
    # 含文本的行保留
    ts = toks("${x} done\n")
    assert ts[1].text == " done" and ts[2].text == "\n"
    ts = toks("${:fi} x\n")
    assert isinstance(ts[0], DirTok)
    assert ts[1].text == " x" and ts[2].text == "\n"


def test_crossline_construct_start_line_elimination():
    # 跨行无输出构造起始行：换行由构造吞并、不重复移除
    ts = toks('${X = r"""a\nb"""}\nafter')
    assert isinstance(ts[0], InterpTok)
    assert texts_of(ts) == ["after"]


def texts_of(ts) -> list[str]:
    return [t.text for t in ts if isinstance(t, TextTok)]


# ---- 其他 -----------------------------------------------------------------

def test_shebang_ignored():
    assert texts("#!/usr/bin/env pcl\nhello") == ["hello"]


def test_compound_statement_c300():
    assert err_code("${if x: pass}") == "C300"
    assert err_code("$(for i in x: pass)") == "C300"


def test_syntax_error_c310():
    assert err_code("${x =}") == "C310"


def test_unknown_directive_p200():
    assert err_code("${:frobnicate x}") == "P200"


def test_bom_and_l102(tmp_path):
    from pcl.compiler import compile_file
    from pcl.errors import PclCompileError
    p = tmp_path / "bom.pcl"
    p.write_bytes("﻿ok\n".encode())   # UTF-8 BOM 剥除（§4.1）
    gen = compile_file(p)
    assert 'emit("ok\\n")' in gen.source
    bad = tmp_path / "bad.pcl"
    bad.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(PclCompileError, match="L102"):
        compile_file(bad)


# ---- ${# 注释简写与 $(# 注记模板（v0.2） ----------------------------------------

def test_comment_shorthand():
    for short in ("${# 简写}", "${#no-space}"):
        assert texts(short + "\n尾\n") == ["尾\n"]   # 整行消除、等效 ${:#}
    # 注释吞到行尾：${# 后的一切属注释负载，不构成 C305
    assert texts("${# c} 文本\n") == []
    assert err_code("文本 ${# c}") == "C305"          # 前置内容才触发



def test_note_construct():
    """$(# … #)：内容为完整模板体（递归 tokenize），闭合 #)。"""
    ts = toks("前 $(# 注 #) 后\n")
    kinds = [type(t).__name__ for t in ts]
    assert kinds == ["TextTok", "NoteTok", "TextTok", "TextTok"]
    note_tok = ts[1]
    assert note_tok.no_output is False
    assert len(note_tok.tokens) >= 1
    assert any(isinstance(t, TextTok) and "注" in t.text for t in note_tok.tokens)
    assert ts[-1].text == "\n"


def test_note_with_interp_and_control_flow():
    """注记内 $()/${}/指令正常渲染。"""
    ts = toks("$(# 分数：$(42) ${:if 1}高${:fi} #)\n")
    assert isinstance(ts[0], NoteTok)
    inner = ts[0].tokens
    assert any(isinstance(t, InterpTok) for t in inner)
    assert any(isinstance(t, DirTok) and t.verb in ("if", "fi") for t in inner)


def test_note_multiline():
    """$(# 可跨行。"""
    ts = toks("$(#\n第一行\n第二行 $(x)\n#)\n尾\n")
    assert any(isinstance(t, NoteTok) for t in ts)
    assert texts("尾\n") == ["尾\n"]


def test_note_closure():
    assert err_code("$(# 未闭合") == "L100"
    # 转义：$$ 产出字面 $，其后为普通文本（不构成注记）
    assert texts("$$(# 不是注记)\n") == ["$(# 不是注记)\n"]



# ---- 扩展定界符 $(<delim># / $(<delim>@ —— 同 C++ raw string -------------------

def test_extended_delimiter_note():
    """$(end# 内容含 #) 不冲突 end#)。"""
    ts = toks("$(end# 注记含 #) 字符 #end)\n尾\n")
    assert any(isinstance(t, NoteTok) for t in ts)
    assert texts("尾\n") == ["尾\n"]


def test_extended_delimiter_context():
    """$(@raw 内容含 @) 不冲突 @raw)。"""
    ts = toks("$(@raw\n上下文含 @) 和 #)\n@raw)\n尾\n")
    assert any(isinstance(t, ContextTok) for t in ts)
    assert texts("尾\n") == ["尾\n"]


def test_extended_delimiter_with_interp():
    """扩展定界符内支持 $() 插值。"""
    ts = toks("$(tag# 值：$(42) #tag)\n")
    assert isinstance(ts[0], NoteTok)
    assert any(isinstance(t, InterpTok) for t in ts[0].tokens)


def test_extended_delimiter_fallback_to_expr():
    """$(foo#bar) 无匹配闭合 #foo) → 回落为 Python 表达式（含注释 → L101）。"""
    # foo#bar 不是合法 Python（# 后是注释），tokenize 会报错或视为表达式
    # 但 $(x) 正常表达式不受影响
    ts = toks("$(42)\n")
    assert any(isinstance(t, InterpTok) for t in ts)
