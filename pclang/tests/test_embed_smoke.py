"""smoke-pi（嵌入形态）：真 pi 会话内 /pcl 命令族（DESIGN §8.5/§9.1）。

经 RPC `prompt` 分发扩展命令（与 TUI 敲 /pcl 等价）。多数用例不需要模型：
gen/version 直通、:save（合成 get_state）、:new → A520、正向专属选项拒绝。
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest

from pcl.pibridge import PiBridge

CONNECTOR = (Path(__file__).resolve().parent.parent.parent
             / "pcl-connector" / "pi" / "extensions" / "index.ts")
PCL_BIN = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "pcl"
DATA = Path(__file__).resolve().parent / "data"

pytestmark = pytest.mark.smoke_pi

requires_pi = pytest.mark.skipif(not shutil.which("pi"), reason="pi 不在 PATH")
requires_pcl = pytest.mark.skipif(not PCL_BIN.exists(), reason="未找到 pcl 可执行")


class _Session:
    """RPC 驱动 /pcl 命令并收集 notify 事件与关键事件计数。"""

    def __init__(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PCL_BIN", str(PCL_BIN))
        self.notifies: list[str] = []
        self.settled = 0
        self.assistant_texts: list[str] = []
        self.bridge = PiBridge(pi_bin="pi", connector_path=str(CONNECTOR),
                               timeout=300)
        # transport 在构造时绑定回调——必须在 start() 前替换实例属性
        orig = self.bridge._handle_frame

        def spy(obj):
            t = obj.get("type")
            if t == "extension_ui_request" and obj.get("method") == "notify":
                self.notifies.append(str(obj.get("message") or ""))
            elif t == "agent_settled":
                self.settled += 1
            elif t in ("message_end", "turn_end"):
                msg = obj.get("message") or {}
                if msg.get("role") == "assistant":
                    text = "".join(b.get("text", "") for b in msg.get("content", [])
                                   if isinstance(b, dict) and b.get("type") == "text")
                    if text:
                        self.assistant_texts.append(text)
            return orig(obj)

        self.bridge._handle_frame = spy
        self.bridge.start()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.bridge.close()

    def wait_settled(self, count: int, timeout: float = 200) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.settled >= count:
                return True
            time.sleep(0.2)
        return self.settled >= count

    def wait_response(self, cid, timeout: float = 200):
        deadline = time.time() + timeout
        with self.bridge._cond:
            while time.time() < deadline:
                resp = self.bridge._responses.get(cid)
                if resp is not None:
                    del self.bridge._responses[cid]
                    return resp
                self.bridge._cond.wait(0.3)
        return None

    def send_raw(self, message: str):
        with self.bridge._lock:
            self.bridge._seq += 1
            cid = self.bridge._seq
        self.bridge._send({"id": cid, "type": "prompt", "message": message})
        return cid

    def send_command(self, message: str, timeout: float = 240):
        b = self.bridge
        with b._lock:
            b._seq += 1
            cid = b._seq
        b._send({"id": cid, "type": "prompt", "message": message})
        deadline = time.time() + timeout
        with b._cond:
            while time.time() < deadline:
                resp = b._responses.get(cid)
                if resp is not None:
                    del b._responses[cid]
                    return resp
                b._cond.wait(0.3)
        return None

    def model_configured(self) -> bool:
        resp = self.bridge._call({"type": "get_state"})
        return bool((resp.get("data") or {}).get("model"))


@requires_pi
@requires_pcl
def test_pcl_gen_passthrough(tmp_path, monkeypatch):
    if not CONNECTOR.exists():  # pragma: no cover
        pytest.skip("pcl-connector/pi 不在预期位置")
    with _Session(tmp_path, monkeypatch) as s:
        resp = s.send_command(f"/pcl gen {DATA / 'demo.pcl'}")
        assert resp is not None and resp.get("success")
        assert any("完成" in n for n in s.notifies)


@requires_pi
@requires_pcl
def test_pcl_version_passthrough(tmp_path, monkeypatch):
    if not CONNECTOR.exists():  # pragma: no cover
        pytest.skip("pcl-connector/pi 不在预期位置")
    with _Session(tmp_path, monkeypatch) as s:
        resp = s.send_command("/pcl version")
        assert resp is not None and resp.get("success")
        # version 直通：notify 即版本文本（一行，无需入会话流）
        assert any(n.startswith("pcl ") for n in s.notifies)


@requires_pi
@requires_pcl
def test_pcl_run_forward_only_rejected(tmp_path, monkeypatch):
    if not CONNECTOR.exists():  # pragma: no cover
        pytest.skip("pcl-connector/pi 不在预期位置")
    with _Session(tmp_path, monkeypatch) as s:
        resp = s.send_command(f"/pcl run {DATA / 'demo.pcl'} --agent null")
        assert resp is not None and resp.get("success")   # 命令本身完成
        assert any("被拒" in n for n in s.notifies)


@requires_pi
@requires_pcl
def test_pcl_run_save_without_model(tmp_path, monkeypatch):
    """:save 冒烟（M3 验收项）：无 pass → 不涉 LLM，token 经合成 get_state 取得。"""
    if not CONNECTOR.exists():  # pragma: no cover
        pytest.skip("pcl-connector/pi 不在预期位置")
    tpl = tmp_path / "save.pcl"
    tpl.write_text("${:save cx}\nLEN=$(len(cx) > 0)\n", encoding="utf-8")
    out = tmp_path / "out.txt"
    with _Session(tmp_path, monkeypatch) as s:
        resp = s.send_command(f"/pcl run {tpl} -o {out}")
        assert resp is not None and resp.get("success")
        assert any("退出码 0" in n for n in s.notifies)
    assert out.read_text(encoding="utf-8") == "LEN=true\n"


@requires_pi
@requires_pcl
def test_pcl_run_new_ctx_now_works(tmp_path, monkeypatch):
    """M4 后 :new 在嵌入形态真正可用（旧 A520 护栏仅对旧版连接器，
    pcl 侧映射由伪嵌入宿主单测覆盖）。"""
    if not CONNECTOR.exists():  # pragma: no cover
        pytest.skip("pcl-connector/pi 不在预期位置")
    tpl = tmp_path / "new.pcl"
    tpl.write_text("A\n${:new}\nB\n", encoding="utf-8")
    out = tmp_path / "out.txt"
    with _Session(tmp_path, monkeypatch) as s:
        resp = s.send_command(f"/pcl run {tpl} -o {out}", timeout=120)
        assert resp is not None and resp.get("success")
        assert any("退出码 0" in n for n in s.notifies)
    assert out.read_text(encoding="utf-8") == "A\nB\n"


@requires_pi
@requires_pcl
def test_pcl_run_embedded_e2e(tmp_path, monkeypatch):
    """/pcl run 全链路：pass + pcl_write 写回 + 分支（真 LLM）。"""
    if not CONNECTOR.exists():  # pragma: no cover
        pytest.skip("pcl-connector/pi 不在预期位置")
    with _Session(tmp_path, monkeypatch) as s:
        if not s.model_configured():
            pytest.skip("未配置模型")
        out = tmp_path / "out.txt"
        resp = s.send_command(
            f"/pcl run {DATA / 'demo.pcl'} 为什么天空是蓝色的 -o {out}")
        assert resp is not None and resp.get("success")
        assert any("退出码 0" in n for n in s.notifies)
        text = out.read_text(encoding="utf-8")
        assert text.startswith("\n")
        assert ("质量达标" in text) or ("分数不够" in text)


# ---- M4：嵌入上下文接续（§8.6） ----------------------------------------------

@requires_pi
@requires_pcl
def test_embed_new_ctx_lands_new_session(tmp_path, monkeypatch):
    """:new → 真会话替换（withSession 接管）→ 后续 pass 落新会话、token 更新。"""
    if not CONNECTOR.exists():  # pragma: no cover
        pytest.skip("pcl-connector/pi 不在预期位置")
    tpl = tmp_path / "newctx.pcl"
    tpl.write_text(
        "${:pass}\n只回复一个字：好\n${:save cx}\n"
        "${:new}\n"
        "${:pass}\n只回复一个字：好\n${:save cx2}\n"
        "SAME=$(cx == cx2)\n", encoding="utf-8")
    out = tmp_path / "out.txt"
    with _Session(tmp_path, monkeypatch) as s:
        if not s.model_configured():
            pytest.skip("未配置模型")
        resp = s.send_command(f"/pcl run {tpl} -o {out}", timeout=300)
        assert resp is not None and resp.get("success")
        assert any("退出码 0" in n for n in s.notifies)
    assert out.read_text(encoding="utf-8").endswith("SAME=false\n")


@requires_pi
@requires_pcl
def test_embed_save_load_roundtrip(tmp_path, monkeypatch):
    """:save → :new → :load（同 cwd）往返；恢复的会话看得到原 pass 内容。"""
    if not CONNECTOR.exists():  # pragma: no cover
        pytest.skip("pcl-connector/pi 不在预期位置")
    tpl = tmp_path / "roundtrip.pcl"
    tpl.write_text(
        "${:pass}\n请只回复一个关键词：蓝色\n${:save cx}\n"
        "${:new}\n"
        "${:load cx}\n"
        "${:pass}\n上一条消息中的关键词是什么？只回复该词。\n",
        encoding="utf-8")
    out = tmp_path / "out.txt"
    with _Session(tmp_path, monkeypatch) as s:
        if not s.model_configured():
            pytest.skip("未配置模型")
        resp = s.send_command(f"/pcl run {tpl} -o {out}", timeout=300)
        assert resp is not None and resp.get("success")
        assert any("退出码 0" in n for n in s.notifies)
    text = out.read_text(encoding="utf-8")
    # 两个 pass 的回复都含关键词——第二个出现在 :load 恢复的会话里（上下文连续）
    assert text.count("蓝色") >= 2


@requires_pi
@requires_pcl
def test_embed_load_cross_cwd_a522(tmp_path, monkeypatch):
    """:load 目标 cwd ≠ 当前 → A522（引导正向 CLI）。"""
    if not CONNECTOR.exists():  # pragma: no cover
        pytest.skip("pcl-connector/pi 不在预期位置")
    # 在别的 cwd 造一个已落盘会话（一次 assistant 回复强制 flush，R20）
    import subprocess as sp
    import threading

    other = tmp_path / "other-cwd"
    other.mkdir()
    p = sp.Popen(["pi", "--mode", "rpc", "--name", "pcl-a522"],
                 stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.DEVNULL,
                 cwd=str(other))
    box: list = []

    def rd():
        for line in p.stdout:
            box.append(json.loads(line))
    threading.Thread(target=rd, daemon=True).start()
    time.sleep(3)
    p.stdin.write((json.dumps({"id": 1, "type": "prompt",
                               "message": "回复：好"}) + "\n").encode())
    p.stdin.flush()
    token = None
    deadline = time.time() + 150
    done = False
    while time.time() < deadline and not done:
        for o in box:
            if o.get("type") == "response" and o.get("id") == 1:
                done = True
        time.sleep(0.3)
    if done:
        p.stdin.write((json.dumps({"id": 2, "type": "get_state"}) + "\n").encode())
        p.stdin.flush()
        time.sleep(1)
        for o in box:
            if o.get("type") == "response" and o.get("id") == 2:
                token = (o.get("data") or {}).get("sessionFile")
    p.stdin.close()
    try:
        p.wait(timeout=10)
    except sp.TimeoutExpired:
        p.kill()
    if not token or not Path(token).is_file():
        pytest.skip("无法构造跨 cwd 会话")

    tpl = tmp_path / "cross.pcl"
    tpl.write_text(f"${{cx = {str(token)!r}}}\n${{:load cx}}\nOK\n", encoding="utf-8")
    out = tmp_path / "out.txt"
    with _Session(tmp_path, monkeypatch) as s:
        resp = s.send_command(f"/pcl run {tpl} -o {out}", timeout=120)
        assert resp is not None and resp.get("success")
        assert any("退出码 3" in n for n in s.notifies)   # A522 → 桥接失败


def _drive_tui(steps: list, settle: float = 6.0, poll: str = "退出码",
                max_wait: float = 180) -> tuple[str, bool]:
    """在 pty 中驱动真 TUI。steps 为指令序列：
    ("send", text) | ("wait", substr, timeout) | ("sleep", secs)。"""
    import fcntl
    import os
    import pty
    import select
    import struct
    import subprocess
    import termios

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
    env = dict(os.environ, TERM="xterm-256color", PCL_BIN=str(PCL_BIN))
    proc = subprocess.Popen(
        ["pi", "-e", str(CONNECTOR)], stdin=slave, stdout=slave, stderr=slave,
        env=env, close_fds=True)
    os.close(slave)
    stream = ""

    def read_all(t: float) -> str:
        nonlocal stream
        buf = b""
        end = time.time() + t
        while time.time() < end:
            r, _, _ = select.select([master], [], [], 0.2)
            if r:
                try:
                    d = os.read(master, 65536)
                    if not d:
                        break
                    buf += d
                except OSError:
                    break
        stream += buf.decode("utf-8", "replace")

    alive = True
    read_all(settle)
    # 就绪等待：出现模型行（页脚）且输出静默 1s——过早写入会被 TUI 吞掉
    ready_deadline = time.time() + 60
    while time.time() < ready_deadline:
        read_all(1.0)
        footer = ("•" in stream) or ("(zai-coding-cn)" in stream)
        if footer and not read_all(0.2):
            break
    for step in steps:
        kind = step[0]
        if kind == "sleep":
            read_all(step[1])
        elif kind == "wait":
            _, substr, timeout = step
            deadline = time.time() + timeout
            while time.time() < deadline and substr not in stream:
                read_all(1.0)
        elif kind == "send":
            try:
                os.write(master, (step[1] + "\r").encode())
            except OSError:
                alive = False
                break
            read_all(0.5)
    deadline = time.time() + max_wait
    while time.time() < deadline:
        read_all(3.0)
        if poll in stream:
            break
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
    return stream, alive


@requires_pi
@requires_pcl
def test_embed_auto_follow_tui_a523(tmp_path, monkeypatch):
    """TUI 用户 /new 中途切换 → auto-follow 接续（L1）→ 后续 :new → A523。"""
    if not CONNECTOR.exists():  # pragma: no cover
        pytest.skip("pcl-connector/pi 不在预期位置")
    monkeypatch.setenv("PCL_BIN", str(PCL_BIN))
    tpl = tmp_path / "follow.pcl"
    tpl.write_text(
        "${import time}\n"
        "${:pass}\n只回复一个字：好\n"
        "${_ = time.sleep(20)}\n"   # 窗口：用户在此期间 /new
        "${:new}\nNEVER\n", encoding="utf-8")
    out = tmp_path / "out.txt"
    stream, alive = _drive_tui([
        ("send", f"/pcl run {tpl} -o {out}"),
        ("wait", "好", 150),          # 等 pass 回复渲染（settled 之后）
        ("sleep", 2.0),
        ("send", "/new"),             # sleep 窗口内用户切换 → auto-follow
        ("wait", "接续", 30),
    ], max_wait=120)
    assert alive
    assert "接续" in stream          # auto-follow 接管提示
    assert "退出码 3" in stream      # 后续 :new → A523 → 桥接失败
