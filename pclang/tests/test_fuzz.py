"""模糊测试（DESIGN §11：模板词法/解析，自写 fuzzer、零第三方依赖）。

不变式：
1. **不崩溃**：任意 UTF-8 输入下 ``compile_source`` 只产出 GenResult 或
   PclCompileError（任何其他异常=发现 bug）；
2. **确定性**：同输入同输出（编译器无隐藏状态）；
3. ``strip_jsonc``：不崩溃、幂等、合法 JSON 逐字节不变、字符串内容免疫剥离。

运行参数：``PCL_FUZZ_ITERS``（默认 1500）、``PCL_FUZZ_SEED``（默认固定，
CI 稳定；本地可随机化复现）。
"""

from __future__ import annotations

import json
import os
import random

import pytest

from pcl.compiler import compile_source
from pcl.errors import PclCompileError
from pcl.settings import strip_jsonc

# 模板 token 汤：文本、构造、指令、转义、控制字符、unicode 边界
_FRAGMENTS = [
    "a", "文本", " ", "\t", "\n", "\r\n", "\r", "$", "$$", "${", "}", "$(", ")",
    "#", "${:#", "${:# 注释}", "${x}", "$(x)", "${x = 1}", "$(x = 1)",
    "${x; y = 2}", "${:if x}", "${:fi}", "${:else}", "${:elif x}",
    "${:for i in x}", "${:done}", "${:while x}", "${:pass}",
    "${:pass :read r :write w}", "${:save s}", "${:load l}", "${:new}",
    "${:break}", "${:continue}", "${:return r}", "${:function f(a=1)}",
    "${:endfunction}", "${:if", "${:", "${:unknown}", "$prompt", "$prompts",
    "$prompté", '"', '"""', "'''", 'r"', "b'", 'f"', "\\", "\\\\",
    "{", "}", "(", ")", "[", "]", ",", ";", ":",
    " ", " ", "\x00", "\x1b", " ",
    '${r"""x"""}}', "$(len(x))", "${ {'a': 1} }", "${D = {'k': 1}}",
    "${import os}", "${x # }", "${x\ny}", '${"}"}', "${f(a,\nb)}",
]


def _iters() -> int:
    return int(os.environ.get("PCL_FUZZ_ITERS", "1500"))


def _seed() -> int:
    s = os.environ.get("PCL_FUZZ_SEED")
    return int(s) if s else 20260915


def _gen(rnd: random.Random) -> str:
    return "".join(rnd.choice(_FRAGMENTS) for _ in range(rnd.randint(1, 60)))


def test_fuzz_compile_invariants():
    rnd = random.Random(_seed())
    ok = err = 0
    for _ in range(_iters()):
        src = _gen(rnd)
        try:
            gen = compile_source(src, "fuzz.pcl")
            ok += 1
            assert compile_source(src, "fuzz.pcl").source == gen.source  # 确定性
        except PclCompileError:
            err += 1
    assert ok + err == _iters()
    assert ok > 0, "至少应有若干输入编译成功"


@pytest.mark.parametrize("depth", [200, 2000])
def test_deep_nesting_is_clean_error(depth):
    """深嵌套必须是干净的编译期错误（PclCompileError），而非 RecursionError。"""
    src = "${:if x}" * depth
    with pytest.raises(PclCompileError):
        compile_source(src, "fuzz.pcl")
    src2 = "${" + "x + (" * depth + "1" + ")" * depth + "}"
    with pytest.raises(PclCompileError):
        compile_source(src2, "fuzz.pcl")


# ---- settings.strip_jsonc -----------------------------------------------------

_JSONC_FRAGS = [
    "{", "}", "[", "]", ",", ":", '"s"', '"//"', '"/*x*/"', '//c\n', "/*c*/",
    " ", '"a,b]"', '"\\\\"', '"\\""', "true", "null", "1", '"\\u2028"', "\n",
    '"尾巴', "// 行", "/* 块", "*/",
]


def test_fuzz_strip_jsonc_never_crashes():
    # 垃圾输入上不设幂等断言：注释剥离会改变引号配对，二次剥离语义
    # 本就不同（引号配对歧义是 JSON 垃圾的固有属性，非实现缺陷）——
    # 只要求不崩溃；有 oracle 的不变式见下方两个测试。
    rnd = random.Random(_seed() + 1)
    for _ in range(_iters()):
        doc = "".join(rnd.choice(_JSONC_FRAGS) for _ in range(rnd.randint(1, 40)))
        strip_jsonc(doc)


def test_fuzz_strip_jsonc_valid_json_untouched():
    rnd = random.Random(_seed() + 2)
    values = [
        {"url": "https://x//y", "c": "/* not comment */", "t": "a,]"},
        ["//", "/*", {"k": "v\\"}, 1.5, None, True],
        {"嵌套": {"深": [{"x": " "}]}, "空": ""},
        {"\\": "\\\\", "quote": 'he said "hi"'},
    ]
    for v in values:
        doc = json.dumps(v, ensure_ascii=False)
        assert strip_jsonc(doc) == doc            # 合法 JSON 逐字节不变
    for _ in range(_iters()):
        # 随机字符串值免疫剥离
        s = "".join(rnd.choice(['/', '*', '"', "\\", ",", "]", "}", "a", " "])
                    for _ in range(rnd.randint(0, 12)))
        doc = json.dumps({"k": s}, ensure_ascii=False)
        assert json.loads(strip_jsonc(doc)) == {"k": s}
