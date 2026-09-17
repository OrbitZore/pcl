"""e2e（script/null 桥）：RFC 0000 §12 示例逐字节断言、reply 折叠、动态嵌套、A510。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcl.bridge import IAgentBridge, PassResult
from pcl.errors import PclCompileError, PclError
from pcl.runtime import run_program

DATA = Path(__file__).resolve().parent / "data"


def run_pcl(path, prompt="", **kw):
    return run_program(str(path), prompt, agent="null", **kw)


# ---- RFC 0000 §12 完整示例 -------------------------------------------------------

def test_rewrite_example_byte_exact(tmp_path):
    script = tmp_path / "s.jsonl"
    script.write_text((DATA / "rewrite.script.jsonl").read_text(encoding="utf-8"),
                      encoding="utf-8")
    result = run_program(str(DATA / "rewrite.pcl"), "为什么天空是蓝色的",
                         agent="script", script=str(script),
                         cache_dir=str(tmp_path / "cache"))
    assert result.output == (
        "\n\n\n"
        "草稿1 正文……\n"
        "草稿2 正文……\n"
        "\n"
        "历史得分：\n"
        "- 5\n"
        "- 8\n"
        "平均（去尾）：6\n"
        "\n"
        "两次自评 5 与 8，第 2 轮达标（均分 6.5）。\n"
    )
    # 模块终态（RunResult.module 可读模板全局）
    m = result.module
    assert m.SCORE == 8 and m.HISTORY == [5, 8]
    assert isinstance(m.cx, str) and m.reply.startswith("两次自评")


def test_rewrite_unwritten_score_unbound_local(tmp_path):
    # agent 不写 SCORE → attempt 内 :return SCORE 为 UnboundLocalError → R400
    # 行号回译取最内层模板帧（:return 在第 10 行）
    script = tmp_path / "s.jsonl"
    script.write_text(json.dumps({"reply": "no write", "writes": {}}) + "\n",
                      encoding="utf-8")
    with pytest.raises(PclError, match="R400") as ei:
        run_program(str(DATA / "rewrite.pcl"), "p", agent="script",
                    script=str(script), cache_dir=str(tmp_path / "cache"))
    assert ei.value.line == 10


# ---- DSL §3 示例（null 桥） ---------------------------------------------------

def test_demo_null_bridge():
    result = run_pcl(DATA / "demo.pcl", "猫为什么会打呼噜")
    assert result.output == (
        "\n"
        "请就以下主题写一段话，并把自评质量分（0..10 整数）写入 SCORE：\n"
        "猫为什么会打呼噜\n"
        "分数不够，重写一遍，把新分数写入 SCORE。\n"
    )
    assert result.module.SCORE == 0  # 未写保持旧值


# ---- reply 尾换行折叠（运行期判定） ---------------------------------------------

def test_reply_fold_with_trailing_newline(tmp_pcl):
    p = tmp_pcl("${:pass}\nbody\n\n")     # EOF 终止；缓冲含尾随空行
    r = run_pcl(p)
    assert r.output == "body\n"           # 折叠补一个 \n（null 桥 reply=trim 后的 body）


def test_reply_fold_without_trailing_newline(tmp_pcl):
    p = tmp_pcl("${:pass}\nbody${''}")    # 体末为插值（无换行尾）→ 不补
    r = run_pcl(p)
    assert r.output == "body"


# ---- 空跳过 / A504 / A510 ------------------------------------------------------

def test_empty_prompt_skip(tmp_pcl):
    p = tmp_pcl("${:if 1}\n${:pass}\n${''}\n${:fi}\nok\n")
    r = run_pcl(p)
    assert r.output == "\nok\n"   # 空 pass → 空结果（折叠出空行）+ 后续文本


def test_script_bridge_exhaustion_a510(tmp_pcl, tmp_path):
    script = tmp_path / "s.jsonl"
    script.write_text('{"reply": "r1", "writes": {}}\n', encoding="utf-8")
    p = tmp_pcl("${:if 1}\n${:pass}\na\n${:fi}${:if 1}\n${:pass}\nb\n${:fi}\n")
    with pytest.raises(PclError, match="A510"):
        run_program(str(p), "", agent="script", script=str(script))


def test_script_empty_reply_a504(tmp_pcl, tmp_path):
    script = tmp_path / "s.jsonl"
    script.write_text('{"reply": "", "writes": {"S": 1}}\n', encoding="utf-8")
    p = tmp_pcl("${:if 1}\n${:pass :write S}\na\n${:fi}\n")
    with pytest.raises(PclError, match="A504"):
        run_program(str(p), "", agent="script", script=str(script))


# ---- 动态嵌套（宏语义，DSL §7） --------------------------------------------------

class _Recorder(IAgentBridge):
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts: list[str] = []

    def submit(self, prompt, reads, writes):
        self.prompts.append(prompt)
        return PassResult(self.replies.pop(0), {})

    def save(self):
        return "t"

    def load(self, token):
        pass

    def new_ctx(self):
        pass


def test_dynamic_nested_pass_ordering(tmp_pcl):
    # ${} 发起型：构造即冲刷点 —— 前置文本先落缓冲，内层 reply 后落（保序）
    p = tmp_pcl(
        "${:function inner}\n"
        "${:pass}\nINNER\n${:return}\n"
        "${:endfunction}\n"
        "${:pass}\nOUT[${_ = inner()}]\n"
    )
    from pcl.importer import import_from_path
    from pcl.runtime import Run
    mod = import_from_path(p)
    bridge = _Recorder(["inner-reply", "outer-reply"])
    with Run(bridge=bridge):
        mod.main("")
    # 提交时序：内层先提交（外层尚在收集体）；外层 prompt 织入内层 reply
    assert bridge.prompts[0] == "INNER"
    assert bridge.prompts[1] == "OUT[inner-reply\n]"


def test_dollar_form_ordering_nested(tmp_pcl):
    # $() 形式：求值副作用先于同段前置文本落缓冲（声明行为，不保序）
    p = tmp_pcl(
        "${:function inner}\n${:pass}\nI\n${:return}\n${:endfunction}\n"
        "${:pass}\nA$(inner())B\n"
    )
    from pcl.importer import import_from_path
    from pcl.runtime import Run
    mod = import_from_path(p)
    bridge = _Recorder(["inner-reply", "outer-reply"])
    with Run(bridge=bridge):
        mod.main("")
    # 内层先提交；外层缓冲序：reply 直落在前，前置文本 "A" 延迟到冲刷点，
    # 取值 None → "null" 织入同段
    assert bridge.prompts[0] == "I"
    assert bridge.prompts[1] == "inner-reply\nAnullB"


# ---- --var / R400 / 上下文 -------------------------------------------------------

def test_var_overrides(tmp_pcl):
    p = tmp_pcl("N=$(N) S=$(S)\n")
    r = run_pcl(p, var_overrides={"N": 5, "S": "hello"})
    assert r.output == "N=5 S=hello\n"


def test_var_reserved_rejected(tmp_pcl):
    for name in ("emit", "prompt", "main", "__pcl_x", "text"):
        with pytest.raises(PclCompileError, match="C300"):
            run_pcl(tmp_pcl("x\n"), var_overrides={name: 1})


def test_runtime_nameerror_translated(tmp_pcl):
    p = tmp_pcl("${undefined_name}\n")
    with pytest.raises(PclError, match="R400") as ei:
        run_pcl(p)
    assert ei.value.line == 1


def test_context_save_load_new(tmp_pcl):
    # 三个 pass 分别由 :save / :load / EOF 终止（指令先提交后执行，§7）
    p = tmp_pcl(
        "${:pass}\nA\n${:save cx}\n"
        "${:new}\n"
        "${:pass}\nB\n${:load cx}\n"
        "${:pass}\nC\n"
    )
    r = run_pcl(p)
    assert r.output == "A\nB\nC\n"
    assert isinstance(r.module.cx, str)


def test_none_expression_emits_null(tmp_pcl):
    r = run_pcl(tmp_pcl("v=${None}\n"))
    assert r.output == "v=null\n"
