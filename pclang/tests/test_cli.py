"""CLI 测试：gen/check/version、退出码、--var、-o、prompt 拼接与 -- 语义。"""

from __future__ import annotations

from pathlib import Path

from pcl.cli import main
from pcl.compiler import compile_program

DATA = Path(__file__).resolve().parent / "data"


def run_cli(argv, capsys):
    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# ---- gen / check / version ----------------------------------------------------

def test_gen_matches_compile_program(capsys, tmp_path):
    code, out, _ = run_cli(["gen", str(DATA / "demo.pcl"), "--cache",
                            str(tmp_path / "c")], capsys)
    assert code == 0
    assert out == compile_program(DATA / "demo.pcl", cache_dir=str(tmp_path / "c2"))


def test_check_ok(capsys, tmp_path):
    code, out, _ = run_cli(["check", str(DATA / "demo.pcl"), "--cache",
                            str(tmp_path / "c")], capsys)
    assert code == 0
    assert out.startswith("OK:")


def test_check_compile_error_exit_1(capsys, tmp_path, tmp_pcl):
    p = tmp_pcl("${x =}\n")
    code, out, err = run_cli(["check", str(p), "--cache", str(tmp_path / "c")], capsys)
    assert code == 1
    assert "[C310]" in err


def test_version(capsys):
    code, out, _ = run_cli(["version"], capsys)
    assert code == 0 and out.startswith("pcl ")


# ---- 用法错退出码 1 --------------------------------------------------------------

def test_usage_error_exit_1(capsys):
    code, _, err = run_cli(["run"], capsys)
    assert code == 1
    code, _, err = run_cli(["frobnicate"], capsys)
    assert code == 1


# ---- run：prompt 拼接 / --var / -o / 退出码 --------------------------------------

def test_run_prompt_joining(capsys, tmp_path, tmp_pcl):
    p = tmp_pcl("P=[$prompt]\n")
    code, out, _ = run_cli(["run", str(p), "hello", "world", "--agent", "null",
                            "--cache", str(tmp_path / "c")], capsys)
    assert code == 0
    assert out == "P=[hello world]\n"


def test_run_prompt_option_and_dashdash(capsys, tmp_path, tmp_pcl):
    p = tmp_pcl("P=[$prompt]\n")
    code, out, _ = run_cli(["run", str(p), "--prompt", "opt", "--agent", "null",
                            "--cache", str(tmp_path / "c")], capsys)
    assert out == "P=[opt]\n"
    # -- 之后的 token 视作位置参数并入 PROMPT、-- 自身移除（选项须在 -- 之前）
    code, out, _ = run_cli(["run", str(p), "--agent", "null",
                            "--cache", str(tmp_path / "c"), "--", "--agent=x"], capsys)
    assert out == "P=[--agent=x]\n"


def test_run_var(capsys, tmp_path, tmp_pcl):
    p = tmp_pcl("N=$(N) S=$(S) F=$(F)\n")
    code, out, _ = run_cli(["run", str(p), "--agent", "null",
                            "--var", "N=5", "--var", "S=hello", "--var", "F='5'",
                            "--cache", str(tmp_path / "c")], capsys)
    assert out == "N=5 S=hello F=5\n"


def test_run_output_file(capsys, tmp_path, tmp_pcl):
    p = tmp_pcl("hello\n")
    o = tmp_path / "out.txt"
    code, out, _ = run_cli(["run", str(p), "--agent", "null", "-o", str(o),
                            "--cache", str(tmp_path / "c")], capsys)
    assert code == 0 and out == ""   # 只写文件、不再打 stdout
    assert o.read_text(encoding="utf-8") == "hello\n"


def test_run_script_agent_e2e(capsys, tmp_path):
    code, out, _ = run_cli(
        ["run", str(DATA / "rewrite.pcl"), "为什么天空是蓝色的",
         "--agent", "script", "--script", str(DATA / "rewrite.script.jsonl"),
         "--cache", str(tmp_path / "c")], capsys)
    assert code == 0
    assert "草稿1 正文……" in out
    assert "平均（去尾）：6" in out


def test_run_runtime_error_exit_2(capsys, tmp_path, tmp_pcl):
    p = tmp_pcl("${boom}\n")
    code, out, err = run_cli(["run", str(p), "--agent", "null",
                              "--cache", str(tmp_path / "c")], capsys)
    assert code == 2
    assert "[R400]" in err


def test_run_bridge_error_exit_3(capsys, tmp_path, tmp_pcl):
    p = tmp_pcl("${:pass}\nx\n")
    script = tmp_path / "empty.jsonl"
    script.write_text("", encoding="utf-8")   # 无条目 → A510
    code, out, err = run_cli(["run", str(p), "--agent", "script",
                              "--script", str(script),
                              "--cache", str(tmp_path / "c")], capsys)
    assert code == 3
    assert "[A510]" in err


def test_run_pi_agent_startup_failure_a5xx(capsys, tmp_path, tmp_pcl):
    # pi 桥已实现（M2）：pi 启动即退 → A 类失败（退出码 3）
    p = tmp_pcl("${:pass}\nx\n")
    code, out, err = run_cli(["run", str(p), "--agent", "pi", "--pi-bin",
                              "/bin/false", "--cache", str(tmp_path / "c")], capsys)
    assert code == 3
    assert "[A50" in err


def test_run_var_reserved_exit_1(capsys, tmp_path, tmp_pcl):
    p = tmp_pcl("x\n")
    code, out, err = run_cli(["run", str(p), "--agent", "null", "--var", "emit=1",
                              "--cache", str(tmp_path / "c")], capsys)
    assert code == 1
    assert "C300" in err


# ---- 缓存 --------------------------------------------------------------------

def test_cache_roundtrip(tmp_path, tmp_pcl, capsys):
    p = tmp_pcl("v1\n")
    c = tmp_path / "cache"
    main(["run", str(p), "--agent", "null", "--cache", str(c)])
    files = list(c.glob("*.pcl.py"))
    assert len(files) == 1
    # 内容变化 → 新 sha → 新条目；同 stem 仅保留最近 2 个
    p.write_text("v2\n", encoding="utf-8")
    main(["run", str(p), "--agent", "null", "--cache", str(c)])
    p.write_text("v3\n", encoding="utf-8")
    main(["run", str(p), "--agent", "null", "--cache", str(c)])
    assert len(list(c.glob("*.pcl.py"))) == 2


def test_cache_none(tmp_pcl, capsys):
    code, out, _ = run_cli(["gen", str(tmp_pcl("ok\n")), "--cache", "none"], capsys)
    assert code == 0 and "emit(" in out
