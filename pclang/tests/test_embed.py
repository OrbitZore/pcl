"""embed 传输（--agent embed）单元测试：伪嵌入宿主经 stdio JSONL 驱动 pcl 子进程。

覆盖：基础 pass + 写回 + 分支、:save（合成 get_state 的 token）、
:load/:new 的 A520（reason=embed-ctx-unsupported）、stdout 协议独占
（${print} 落 stderr 不污染协议流）、强制 -o、运行期错误退出码 2。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
EMBED_HOST = TESTS / "embed_host.py"
DATA = TESTS / "data"
PCL_BIN = str(TESTS.parent / ".venv" / "bin" / "pcl")


def run_embed(tmp_path, cfg: dict) -> tuple[int, str, bool, str]:
    out = tmp_path / "out.txt"
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(EMBED_HOST), PCL_BIN, str(out), str(cfg_path)],
        capture_output=True, text=True, timeout=120, cwd=str(TESTS.parent))
    exit_code = None
    stderr_tail = ""
    out_exists = False
    for line in proc.stdout.splitlines():
        if line.startswith("EXIT:"):
            exit_code = int(line.split(":", 1)[1].strip())
        elif line.startswith("STDERR:"):
            stderr_tail = line.split(":", 1)[1]
        elif line.startswith("OUT-EXISTS:"):
            out_exists = line.split(":", 1)[1].strip() == "True"
    out_text = out.read_text(encoding="utf-8") if out.exists() else ""
    return exit_code, stderr_tail, out_exists, out_text


@pytest.mark.skipif(not Path(PCL_BIN).exists(), reason="未找到 pcl 可执行")
def test_embed_basic_pass_write(tmp_path):
    code, _, exists, text = run_embed(tmp_path, {
        "file": str(DATA / "demo.pcl"),
        "prompt": "你好",
        "passes": [{"reply": "完成，已写入 SCORE：8", "writes": {"SCORE": 8}}],
    })
    assert code == 0 and exists
    assert text.startswith("\n")           # demo.pcl 行 3 空行
    assert "完成，已写入 SCORE：8\n" in text  # reply + 尾换行折叠
    assert "质量达标" in text               # SCORE=8 ≥ 7 → if 分支


@pytest.mark.skipif(not Path(PCL_BIN).exists(), reason="未找到 pcl 可执行")
def test_embed_save_synthesizes_token(tmp_path):
    tpl = tmp_path / "save.pcl"
    tpl.write_text("${:save cx}\nLEN=$(len(cx) > 0)\n", encoding="-utf-8" if False else "utf-8")
    code, _, exists, text = run_embed(tmp_path, {
        "file": str(tpl),
        "sessionFile": "/tmp/fake-embed-session.jsonl",
        "passes": [],
    })
    assert code == 0
    assert text == "LEN=true\n"            # :save 经合成 get_state 取 token（bool → true，§10）


@pytest.mark.skipif(not Path(PCL_BIN).exists(), reason="未找到 pcl 可执行")
def test_embed_new_ctx_a520(tmp_path):
    tpl = tmp_path / "new.pcl"
    tpl.write_text("A\n${:new}\nB\n", encoding="utf-8")
    code, stderr, _, _ = run_embed(tmp_path, {"file": str(tpl), "passes": []})
    assert code == 3                       # 桥接 A 类
    assert "A520" in stderr


@pytest.mark.skipif(not Path(PCL_BIN).exists(), reason="未找到 pcl 可执行")
def test_embed_stdout_exclusive(tmp_path):
    # ${print} 落 stderr（协议独占 stdout）；若污染协议流，宿主帧解析将失败
    tpl = tmp_path / "print.pcl"
    tpl.write_text("${_ = print('side effect')}\nOK\n", encoding="utf-8")
    code, stderr, exists, text = run_embed(tmp_path, {"file": str(tpl), "passes": []})
    assert code == 0
    assert text == "OK\n"
    assert "side effect" in stderr


@pytest.mark.skipif(not Path(PCL_BIN).exists(), reason="未找到 pcl 可执行")
def test_embed_requires_output_file(tmp_path):
    tpl = tmp_path / "t.pcl"
    tpl.write_text("x\n", encoding="utf-8")
    proc = subprocess.run(
        [PCL_BIN, "run", str(tpl), "--agent", "embed", "--cache", "none"],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1
    assert "强制 -o" in proc.stderr


@pytest.mark.skipif(not Path(PCL_BIN).exists(), reason="未找到 pcl 可执行")
def test_embed_runtime_error_exit_2(tmp_path):
    tpl = tmp_path / "boom.pcl"
    tpl.write_text("${undefined_name}\n", encoding="utf-8")
    code, stderr, _, _ = run_embed(tmp_path, {"file": str(tpl), "passes": []})
    assert code == 2
    assert "R400" in stderr


@pytest.mark.skipif(not Path(PCL_BIN).exists(), reason="未找到 pcl 可执行")
def test_embed_picks_up_project_settings(tmp_path, monkeypatch):
    """嵌入子进程按模板路径发现项目级设置（SETTINGS §2/验收 9）。

    项目级 {"trace": true} → embed 桥经 tracer 把 message_update 增量
    写到 stderr（协议独占 stdout 不受影响）。
    """
    import os

    proj = tmp_path / "proj"
    (proj / ".pcl").mkdir(parents=True)
    (proj / ".pcl" / "settings.json").write_text('{"trace": true}', encoding="utf-8")
    tpl = proj / "t.pcl"
    tpl.write_text("${:pass}\nOK\n", encoding="utf-8")   # EOF 终止的 pass

    out = tmp_path / "out.txt"
    cfg_path = tmp_path / "cfg.json"
    # embed_host 直驱 pcl 子进程：经 extra_event 发送 message_update
    cfg_path.write_text(json.dumps({
        "file": str(tpl), "passes": [{}],
        "extra_event": {"type": "message_update",
                        "assistantMessageEvent": {"type": "text_delta",
                                                  "delta": "TRACE-DELTA"}},
    }), encoding="utf-8")

    host = TESTS / "embed_host.py"
    proc = subprocess.run(
        [sys.executable, str(host), PCL_BIN, str(out), str(cfg_path)],
        capture_output=True, text=True, timeout=120, cwd=str(TESTS.parent),
        env={**os.environ, "XDG_CONFIG_HOME": str(tmp_path / "no-user-cfg"),
             "PCL_CONFIG_FILE": "", "PCL_NO_PROJECT_CONFIG": ""})
    assert "EXIT: 0" in proc.stdout
    assert out.read_text(encoding="utf-8") == "ok\n"   # null 回放 reply + 折叠
    assert "TRACE-DELTA" in proc.stdout    # trace 增量落 stderr（host 汇报）
