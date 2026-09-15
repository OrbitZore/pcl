"""tparse 单元测试：块配对、位置违例、指令参数、保留名、提升判定。"""

from __future__ import annotations

import pytest

from pcl.compiler import compile_source
from pcl.errors import PclCompileError


def err(src: str) -> PclCompileError:
    with pytest.raises(PclCompileError) as ei:
        compile_source(src, "t.pcl")
    return ei.value


def code(src: str) -> str:
    return err(src).code


# ---- P201 块配对与位置违例 -------------------------------------------------

def test_block_pairing():
    assert code("${:if x}\n${:fi}${:fi}") == "P201"          # 多余 :fi
    assert code("${:if x}") == "P201"                        # 缺 :fi
    assert code("${:while x}") == "P201"                     # 缺 :done
    assert code("${:for x in y}") == "P201"
    assert code("${:function f}") == "P201"
    assert code("${:else}") == "P201"
    assert code("${:elif x}") == "P201"
    assert code("${:done}") == "P201"
    assert code("${:fi}") == "P201"
    assert code("${:endfunction}") == "P201"
    assert code("${:if x}\na${:else}\nb${:elif y}\nc${:fi}") == "P201"
    assert code("${:if x}\na${:else}\nb${:else}\nc${:fi}") == "P201"


def test_position_violations():
    assert code("${:break}") == "P201"
    assert code("${:continue}") == "P201"
    assert code("${:return 1}") == "P201"
    assert code("${:if x}${:function f}${:endfunction}${:fi}") == "P201"
    assert code("${:function f}${:function g}${:endfunction}${:endfunction}") == "P201"
    # 函数内的 break/continue 不受外层循环影响（词法作用域）
    assert code("${:function f}${:break}${:endfunction}") == "P201"
    assert code("${:function f}${:for i in x}${:done}${:break}${:endfunction}") == "P201"
    # 合法：循环内 break；函数内循环+break；函数内 return
    compile_source("${:for i in x}${:break}${:done}", "t.pcl")
    compile_source("${:function f}${:for i in x}${:break}${:done}${:endfunction}", "t.pcl")
    compile_source("${:function f}${:return 1}${:endfunction}", "t.pcl")


# ---- P200 指令参数 ---------------------------------------------------------

def test_directive_args():
    assert code("${:pass :read 5}") == "P200"
    assert code("${:pass :write 'x'}") == "P200"
    assert code("${:pass :read a.b}") == "P200"
    assert code("${:pass :read a :read b}") == "P200"
    assert code("${:save 5}") == "P200"
    assert code("${:save 'x'}") == "P200"
    assert code("${:load x.y}") == "P200"
    assert code("${:if}") == "P200"
    assert code("${:while}") == "P200"
    assert code("${:for}") == "P200"
    assert code("${:if x}${:elif}${:fi}") == "P200"
    assert code("${:if x}${:else y}${:fi}") == "P200"
    assert code("${:new x}") == "P200"
    assert code("${:function class}") == "P200"
    assert code("${:pass :read class}") == "P200"
    # 括号不配平的参数 → 构造无法闭合（§4.2）
    assert code("${:function f(}") == "L100"


def test_pass_flag_order_free():
    compile_source("${:if 1}\n${:pass :write S :read C}\nx\n${:fi}", "t.pcl")
    compile_source("${:if 1}\n${:pass :read C :write S}\nx\n${:fi}", "t.pcl")


# ---- P202 / P203 -----------------------------------------------------------

def test_p202_empty_pass_body():
    assert code("${:if 1}${:pass}\n${:fi}") == "P202"
    assert code("${:pass :write S}") == "P202"


def test_p203_pass_body_control_flow():
    assert code("${:if 1}${:pass}\n${break}\n${:fi}${:fi}") == "P203"
    assert code("${:if 1}${:pass}\n$(return 1)\n${:fi}${:fi}") == "P203"
    assert code("${:if 1}${:pass}\n$(continue)\n${:fi}${:fi}") == "P203"
    # yield 不在拦截之列（生成器语义，DSL §7）
    compile_source(
        "${:function f}${:pass}\n${(yield 1)}\n${:return}\n${:endfunction}", "t.pcl")


# ---- C300 ------------------------------------------------------------------

def test_function_reserved_names():
    assert code("${:function main}") == "C300"
    assert code("${:function prompt}") == "C300"
    assert code("${:function reply}") == "C300"


def test_runtime_reserved_binding_targets():
    for src in (
        "${emit = 1}", "${text, x = 1, 2}", "${submit += 1}", "${save: int = 1}",
        "${load = 1}", "${new_ctx = 1}", "${push_sink = 1}", "${pop_sink = 1}",
        "${(submit := 1)}", "${del emit}", "${import os as text}",
        "${from os import path as save}",
        "${:for emit in x}${:done}", "${:save text}",
        "${:if 1}${:pass :write load}\nx\n${:fi}",
        "${:function f(emit)}${:endfunction}", "${:function __pcl_x()}${:endfunction}",
        "${__pcl_t = 1}",
    ):
        assert code(src) == "C300", src


def test_prompt_reply_not_reserved_as_targets():
    compile_source("${prompt = 1}${reply = 2}", "t.pcl")
    compile_source("${:if 1}${:pass :write reply}\nx\n${:fi}", "t.pcl")


def test_import_star_position():
    assert code("${:if x}${from os import *}${:fi}") == "C300"
    # 混排非 import/字面量语句 → 不可提升 → C300
    assert code("${from os import *; V = f()}") == "C300"
    assert code("${:function f}${from os import *}${:endfunction}") == "C300"
    compile_source("${from os import *}", "t.pcl")   # 顶层单行合法
    # import 之间混排（整体可提升）合法
    compile_source("${from math import floor; from os import *}", "t.pcl")


# ---- 提升判定（§9.2） --------------------------------------------------------

def test_promotion_literals():
    src = compile_source(
        "${X = -5}\n${Y = [1, 2, (3,)]}\n${Z = 1+2}\n${W: int = 5}\n${V = x}",
        "t.pcl").source
    assert "X = -5  # pcl:1" in src
    assert "Y = [1, 2, (3,)]  # pcl:2" in src
    assert "Z = 1+2  # pcl:3" in src.split("def main")[1]
    assert "W: int = 5  # pcl:4" in src.split("def main")[1]
    assert "V = x  # pcl:5" in src.split("def main")[1]


def test_promotion_mixed_import_and_literal():
    src = compile_source("${import json; N = 3}", "t.pcl").source
    assert "import json  # pcl:1" in src
    assert "N = 3  # pcl:1" in src


def test_annassign_not_in_global_union():
    src = compile_source("${W: int = 5}", "t.pcl").source
    glob = [ln for ln in src.splitlines() if ln.strip().startswith("global ")][0]
    assert "W" not in glob   # Python 禁止 global 与注解赋值同现


# ---- 空块体 → pass ----------------------------------------------------------

def test_empty_blocks():
    src = compile_source("${:if x}${:fi}", "t.pcl").source
    assert "        pass" in src
    compile_source("${:while x}${:done}", "t.pcl")
    compile_source("${:for i in x}${:done}", "t.pcl")
    compile_source("${:function f}${:endfunction}", "t.pcl")
