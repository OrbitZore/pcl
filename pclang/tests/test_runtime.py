"""runtime 单元测试：text()/freeze、submit 语义、sink 栈、R405。"""

from __future__ import annotations

import pytest

from pcl import runtime
from pcl.bridge import IAgentBridge, PassResult
from pcl.errors import PclError
from pcl.runtime import Run, __pcl_freeze, text

# ---- text()（DSL §10） ------------------------------------------------------

def test_text_scalars():
    assert text("abc") == "abc"
    assert text(None) == "null"
    assert text(True) == "true"
    assert text(False) == "false"
    assert text(1) == "1"
    assert text(-42) == "-42"
    assert text(1.5) == "1.5"
    assert text(0.1) == repr(0.1)


def test_text_containers():
    assert text([1, "a", None]) == '[1,"a",null]'
    assert text((1, 2)) == "[1,2]"          # tuple 视作 list
    assert text({"k": 1}) == '{"k":1}'
    assert text({}) == "{}"
    assert text([[1], {"a": [2]}]) == '[[1],{"a":[2]}]'
    # 键按插入序；非字符串键按 JSON 惯例字符串化
    assert text({1: "a", "b": 2}) == '{"1":"a","b":2}'
    assert text({True: "a"}) == '{"true":"a"}'
    assert text({None: "a"}) == '{"null":"a"}'
    assert text({1.5: "a"}) == '{"1.5":"a"}'
    # 其余键 str() 兜底
    assert text({(1, 2): "a"}) == '{"(1, 2)":"a"}'


def test_text_key_collision_falls_back():
    assert text({1: "a", "1": "b"}) == str({1: "a", "1": "b"})
    assert text({(1, 2): "a", "(1, 2)": "b"}) == str({(1, 2): "a", "(1, 2)": "b"})


def test_text_nan_inf_fallback():
    assert text(float("nan")) == "nan"       # 顶层 float → repr
    assert text(float("inf")) == "inf"
    assert text([float("nan"), 1]) == '["nan",1]'
    assert text({"a": float("-inf")}) == '{"a":"-inf"}'
    assert text({float("nan"): 1}) == '{"nan":1}'


def test_text_unserializable_fallback():
    class Obj:
        def __str__(self):
            return "<Obj>"

    assert text(Obj()) == "<Obj>"
    assert text([Obj()]) == '["<Obj>"]'


def test_text_circular():
    a = [1]
    a.append(a)
    # 循环节点以 str() 兜底、外层容器结构保留（§10）
    assert text(a) == '[1,"[1, [...]]"]'



# ---- __pcl_freeze（:read 快照） ----------------------------------------------

def test_freeze_containers_preserved():
    v = {"list": [1, (2, 3)], "d": {"x": 1}}
    f = __pcl_freeze(v)
    assert f == {"list": [1, [2, 3]], "d": {"x": 1}}
    assert isinstance(f["list"][1], list)   # tuple → list（JSON-safe）
    assert __pcl_freeze(5) == 5
    assert __pcl_freeze("s") == "s"
    assert __pcl_freeze(None) is None
    assert __pcl_freeze(float("nan")) == "nan"
    assert __pcl_freeze(object())  # str() 兜底
    a = [1]
    a.append(a)
    assert __pcl_freeze(a) == [1, "[1, [...]]"]  # 循环节点兜底、外层保留


# ---- submit 语义 ------------------------------------------------------------

class _CountingBridge(IAgentBridge):
    def __init__(self, reply="R", writes=None):
        self.reply = reply
        self.writes = writes or {}
        self.calls: list[tuple] = []

    def submit(self, prompt, reads, writes):
        self.calls.append((prompt, reads, writes))
        return PassResult(self.reply, dict(self.writes))

    def save(self):
        return "tok"

    def load(self, token):
        if token != "tok":
            raise PclError("R430", "未知 token")

    def new_ctx(self):
        pass


def _run_with(bridge):
    return Run(bridge=bridge)


def test_submit_trims_and_passes():
    b = _CountingBridge()
    with _run_with(b):
        r = runtime.submit("  \n prompt \t\n ", {"A": 1}, ("W",))
    assert b.calls == [("prompt", {"A": 1}, ("W",))]
    assert r.reply == "R"


def test_submit_fullwidth_only_prompt_not_empty():
    b = _CountingBridge()
    with _run_with(b):
        runtime.submit("　", {}, ())   # 全角空白不剥、不判空
    assert len(b.calls) == 1


def test_submit_empty_prompt_skips_bridge():
    b = _CountingBridge()
    with _run_with(b):
        r = runtime.submit("  \n\t ", {}, ())
    assert b.calls == []
    assert r.reply == "" and r.writes == {}


def test_submit_unauthorized_write_r406_before_a504():
    b = _CountingBridge(reply="", writes={"OTHER": 1})  # 越权 + 空回复并存
    with _run_with(b):
        with pytest.raises(PclError, match="R406"):
            runtime.submit("p", {}, ())


def test_submit_empty_reply_a504():
    b = _CountingBridge(reply="")
    with _run_with(b):
        with pytest.raises(PclError, match="A504"):
            runtime.submit("p", {}, ())


def test_submit_depth_limit_r400():
    v = cur = {}
    for _ in range(33):
        cur["n"] = {}
        cur = cur["n"]
    b = _CountingBridge(writes={"W": v})
    with _run_with(b):
        with pytest.raises(PclError, match="R400"):
            runtime.submit("p", {}, ("W",))


# ---- R405 / sink 栈 -----------------------------------------------------------

def test_r405_without_run():
    calls = [
        lambda: runtime.emit("x"),
        runtime.push_sink,
        runtime.pop_sink,
        lambda: runtime.submit("x", {}, ()),
        runtime.save,
        runtime.new_ctx,
    ]
    for call in calls:
        with pytest.raises(PclError, match="R405"):
            call()


def test_sink_stack():
    with _run_with(_CountingBridge()):
        runtime.emit("a")
        runtime.push_sink()
        runtime.emit("b")
        runtime.push_sink()
        runtime.emit("c")
        assert runtime.pop_sink() == "c"
        assert runtime.pop_sink() == "b"
        runtime.emit("d")
    # Run.output 在退出上下文后仍可读
    assert True


def test_run_output_collection():
    r = Run(bridge=_CountingBridge())
    with r:
        runtime.emit("hello")
        assert r.output == "hello"  # 逐段累积，末尾取全文
    assert r.output == "hello"


def test_run_out_streaming():
    chunks = []
    r = Run(bridge=_CountingBridge(), out=chunks.append)
    with r:
        runtime.emit("a")
        runtime.emit("b")
        runtime.push_sink()
        runtime.emit("inner")   # sink 内不外流
        runtime.pop_sink()
    assert chunks == ["a", "b"]
    assert r.output == "ab"


def test_load_non_str_r431():
    with _run_with(_CountingBridge()):
        with pytest.raises(PclError, match="R431"):
            runtime.load(123)


def test_load_stale_token_r430():
    with _run_with(_CountingBridge()):
        with pytest.raises(PclError, match="R430"):
            runtime.load("nope")
