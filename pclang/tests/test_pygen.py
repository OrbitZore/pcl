"""pygen 测试：黄金快照、发射模型、global 并集、模块布局、\\r 转义保真。"""

from __future__ import annotations

from pathlib import Path

import pytest

from pcl.compiler import compile_source

GOLDEN = Path(__file__).resolve().parent / "golden"
DATA = Path(__file__).resolve().parent / "data"


# ---- 黄金快照（M0 验收：DSL §3 生成源与文档一致） ---------------------------

@pytest.mark.parametrize("name", ["demo", "rewrite"])
def test_golden(name):
    src = (DATA / f"{name}.pcl").read_text(encoding="utf-8")
    gen = compile_source(src, f"{name}.pcl")
    expected = (GOLDEN / f"{name}.gen.py").read_text(encoding="utf-8")
    assert gen.source == expected


# ---- 发射模型（§5.2） -------------------------------------------------------

def test_initiator_flush_and_independent_emit():
    src = compile_source("a${x}b$(y)c\n", "t.pcl").source
    body = src.split("prompt = __pcl_prompt", 1)[1]
    # ${} 先冲刷（"a"）→ 独立 emit(text(x)) → "b" + 暂存 + "c" 合并单条 emit
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    assert 'emit("a")  # pcl:1' in lines
    assert "emit(text(x))  # pcl:1" in lines
    assert any(ln.startswith("__pcl_t1 = text(y)") for ln in lines)
    assert 'emit("b" + __pcl_t1 + "c\\n")  # pcl:1' in lines


def test_merge_segment_range_comment():
    src = compile_source("一\n$(x)\n二\n", "t.pcl").source
    assert '# pcl:1-3' in src


def test_statements_order_in_initiator():
    src = compile_source("${a = 1; f(a); b = f(a)}", "t.pcl").source
    body = src.split("def main", 1)[1]
    assert "a = 1" in body
    assert "emit(text(f(a)))" in body
    assert "b = f(a)" in body
    assert body.index("a = 1") < body.index("emit(text(f(a)))") < body.index("b = f(a)")


def test_merge_does_not_flush_but_stmts_execute_immediately():
    # $(s = prompt) 非字面量赋值不提升；语句立即执行、文本延迟到冲刷点
    src = compile_source("pre $(s = prompt) post\n", "t.pcl").source
    body = src.split("def main", 1)[1]
    assert body.index("s = prompt") < body.index('emit("pre')
    assert 'emit("pre  post\\n")' in body


# ---- global 并集（§9.2） -----------------------------------------------------

def test_main_globals_union():
    src = compile_source(
        "${:for i, (j, k) in x}\n${del m}\n${(w := 1)}${[q for z in y if (h := 1)]}\n"
        "${import os as sys2}\n${n += 1}\n${:save cx}\n"
        "${:if a}${:pass :write WS}\nbody\n${:fi}${:done}",
        "t.pcl").source
    glob = [ln for ln in src.splitlines() if ln.strip().startswith("global ")][0]
    for name in ("reply", "i", "j", "k", "m", "w", "h", "sys2", "n", "cx", "WS"):
        assert name in glob, name
    assert "q" not in glob   # 推导式迭代变量不绑定
    assert "z" not in glob
    assert "prompt" in glob


def test_function_bindings_not_in_main_globals():
    src = compile_source("${:function f(loc)}${loc = 1}${:endfunction}", "t.pcl").source
    glob = [ln for ln in src.splitlines() if ln.strip().startswith("global ")][0]
    assert "loc" not in glob


def test_pass_read_freeze_before_push_sink():
    src = compile_source("${:if 1}${:pass :read C}\np\n${:fi}", "t.pcl").source
    i_read = src.index('__pcl_reads = {"C": __pcl_freeze(C)}')
    i_push = src.index("push_sink()")
    assert i_read < i_push


def test_pass_submit_sequence_and_fold():
    src = compile_source("${:if 1}${:pass :write S}\np\n${:fi}", "t.pcl").source
    for frag in ('__pcl_buf = pop_sink()',
                 '__pcl_r = submit(__pcl_buf, writes=("S",))',
                 'reply = __pcl_r.reply',
                 'if "S" in __pcl_r.writes: S = __pcl_r.writes["S"]',
                 'emit(reply + ("\\n" if __pcl_buf.endswith("\\n") else ""))'):
        assert frag in src


def test_pass_no_read_write_omits_kwargs():
    src = compile_source("${:if 1}${:pass}\np\n${:fi}", "t.pcl").source
    assert "submit(__pcl_buf)" in src


def test_header_imports_filtered():
    src = compile_source("${x}", "t.pcl").source
    assert "from pcl.runtime import emit, text" in src
    src = compile_source("${:new}", "t.pcl").source
    assert "new_ctx" in src.splitlines()[1]


# ---- \\r 转义保真（R21） ------------------------------------------------------

def test_cr_escaped_in_text_constant():
    gen = compile_source("a\rb\n", "t.pcl")
    assert '"a\\rb\\n"' in gen.source


def test_cr_preserved_in_raw_triple_string():
    gen = compile_source('${r"""a\r\nb"""}', "t.pcl")
    # 生成源须以转义形式保住 \r（tokenizer 会把裸 \r 规范化为 \n）
    assert '"a\\r\\nb"' in gen.source


# ---- 加载层与 main 布局 -------------------------------------------------------

def test_load_layer_source_order():
    src = compile_source(
        "${A = 1}\n${:function f}\nbody\n${:endfunction}\n${B = 2}\nafter\n",
        "t.pcl").source
    load = src.split("def main", 1)[0]
    assert load.index("A = 1") < load.index("def f(prompt=") < load.index("B = 2")


def test_empty_template():
    src = compile_source("", "t.pcl").source
    assert "def main(__pcl_prompt=\"\"):" in src
    assert "pass" in src
