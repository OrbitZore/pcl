"""pibridge 单元测试：以伪 JSONL 对端（fake pi）驱动状态机（DESIGN §8.1–8.4）。

伪对端按脚本化 JSON 配置回放：pass 事件序（writes → message_update →
message_end → agent_settled → response ok，严格次序）、上下文命令响应。
"""

from __future__ import annotations

import json
import stat
import textwrap
import time
from pathlib import Path

import pytest

from pcl.bridge import PassResult  # noqa: F401
from pcl.errors import PclError
from pcl.pibridge import PiBridge
from pcl.runtime import Run
from pcl.runtime import submit as rt_submit

FAKE_PI = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, sys

    def send(obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\\n")
        sys.stdout.flush()

    def log(kind, data):
        with open(os.environ["FAKE_PI_LOG"], "a", encoding="utf-8") as f:
            f.write(json.dumps({"kind": kind, "data": data}, ensure_ascii=False) + "\\n")

    cfg = json.loads(open(os.environ["FAKE_PI_SCRIPT"], encoding="utf-8").read())
    passes = list(cfg.get("passes", []))
    fdir = os.environ.get("FAKE_PI_DIR", "/tmp/fake")
    state = dict(cfg.get("state", {"sessionFile": fdir + "/session-aaa.jsonl"}))
    last_reply = None
    new_seq = 0

    for raw in sys.stdin:
        line = raw.rstrip("\\n")
        if line.endswith("\\r"):
            line = line[:-1]
        try:
            cmd = json.loads(line)
        except ValueError:
            continue
        t = cmd.get("type")
        cid = cmd.get("id")
        if t == "get_state":
            send({"id": cid, "type": "response", "command": "get_state",
                  "success": True, "data": dict(state)})
        elif t == "get_commands":
            send({"id": cid, "type": "response", "command": "get_commands",
                  "success": True,
                  "data": {"commands": cfg.get("commands",
                                               [{"name": "pcl", "source": "extension"}])}})
        elif t == "set_session_name":
            state["sessionName"] = cmd["name"]
            log("set_session_name", cmd["name"])
            if cfg.get("rotate_on_name"):
                state["sessionFile"] = cfg["rotate_on_name"]
            send({"id": cid, "type": "response", "command": "set_session_name",
                  "success": True})
        elif t == "get_last_assistant_text":
            text = None if cfg.get("reply_null") else last_reply
            send({"id": cid, "type": "response", "command": "get_last_assistant_text",
                  "success": True, "data": {"text": text}})
        elif t == "new_session":
            new_seq += 1
            cancelled = bool(cfg.get("new_cancelled"))
            if not cancelled:
                state["sessionFile"] = f"{fdir}/new-{new_seq}.jsonl"
            send({"id": cid, "type": "response", "command": "new_session",
                  "success": True, "data": {"cancelled": cancelled}})
        elif t == "switch_session":
            log("switch_session", cmd.get("sessionPath"))
            if cfg.get("switch_fail"):
                send({"id": cid, "type": "response", "command": "switch_session",
                      "success": False, "error": "cannot open"})
            else:
                cancelled = bool(cfg.get("switch_cancelled"))
                if not cancelled:
                    state["sessionFile"] = cmd.get("sessionPath")
                send({"id": cid, "type": "response", "command": "switch_session",
                      "success": True, "data": {"cancelled": cancelled}})
        elif t == "abort":
            log("abort", None)
            send({"id": cid, "type": "response", "command": "abort", "success": True})
        elif t == "prompt":
            msg = cmd.get("message", "")
            log("prompt", msg)
            if msg.startswith("/pcl pass "):
                payload = json.loads(msg[len("/pcl pass "):])
                log("pass_payload", payload)
                p = passes.pop(0) if passes else {}
                for name, val in (p.get("writes") or {}).items():
                    send({"type": "tool_execution_start", "toolCallId": "c1",
                          "toolName": "pcl_write", "args": {name: val}})
                for name, val in (p.get("writes_more") or {}).items():
                    send({"type": "tool_execution_start", "toolCallId": "c2",
                          "toolName": "pcl_write", "args": {name: val}})
                reply = p.get("reply", "")
                if reply:
                    if p.get("partial_delta"):
                        send({"type": "message_update", "assistantMessageEvent":
                              {"type": "text_delta", "delta": p["partial_delta"]}})
                    last_reply = reply
                    send({"type": "message_end", "message": {"role": "assistant",
                          "content": [{"type": "text", "text": reply}]}})
                else:
                    last_reply = None
                if p.get("extension_error"):
                    send({"type": "extension_error",
                          "extensionPath": "command:pcl", "event": "command",
                          "error": p["extension_error"]})
                if p.get("other_extension_error"):
                    send({"type": "extension_error",
                          "extensionPath": "/path/other.ts", "event": "tool_call",
                          "error": "unrelated"})
                if p.get("response_ok", True) is False:
                    # 预检失败：无 agent 运行、response 为 error（§8.2）
                    send({"id": cid, "type": "response", "command": "prompt",
                          "success": False,
                          "error": p.get("response_error", "preflight failed")})
                elif not p.get("never_settle"):
                    # 真实次序（M2 冒烟实测）：response ok 在预检通过时即发、
                    # 早于 settled；settled 才是 pass 边界。response_late 可反转验证。
                    frames_ok = [{"id": cid, "type": "response",
                                  "command": "prompt", "success": True}]
                    frames_settled = [{"type": "agent_settled"}]
                    for f in (frames_settled + frames_ok if p.get("response_late")
                              else frames_ok + frames_settled):
                        send(f)
                # never_settle：settled 与 response 均不发（纯超时路径）
                if p.get("exit_after"):
                    sys.exit(3)
            else:
                send({"id": cid, "type": "response", "command": "prompt",
                      "success": False, "error": "not a pcl command"})
        else:
            send({"id": cid, "type": "response", "command": t,
                  "success": False, "error": "unknown command"})
''')


@pytest.fixture
def fake_pi(tmp_path, monkeypatch):
    """写入伪 pi 可执行脚本；返回 (pi_bin, 写配置函数)。"""
    script = tmp_path / "fake-pi"
    script.write_text(FAKE_PI, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "log.jsonl"
    log.write_text("", encoding="utf-8")
    monkeypatch.setenv("FAKE_PI_LOG", str(log))
    (tmp_path / "fdir").mkdir(exist_ok=True)
    monkeypatch.setenv("FAKE_PI_DIR", str(tmp_path / "fdir"))

    def configure(cfg: dict) -> str:
        cfg_path = tmp_path / f"cfg-{len(list(tmp_path.glob('cfg-*.json')))}.json"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        monkeypatch.setenv("FAKE_PI_SCRIPT", str(cfg_path))
        return str(script)

    configure.log = log
    return configure


def read_log(fixture) -> list[dict]:
    out = []
    # 仅按 \n 切分：U+2028/U+2029 在 JSON 字符串内合法，不能用 splitlines
    for line in Path(fixture.log).read_text(encoding="utf-8").split("\n"):
        if line.strip():
            out.append(json.loads(line))
    return out


def make_bridge(pi_bin: str, **kw) -> PiBridge:
    return PiBridge(pi_bin=pi_bin, timeout=kw.pop("timeout", 5.0), **kw)


# ---- 就绪探测（§8.1） ---------------------------------------------------------

def test_probe_ok_and_payload(fake_pi):
    bin_ = fake_pi({"passes": [{"reply": "好的", "writes": {"S": 5}}]})
    b = make_bridge(bin_)
    b.start()
    try:
        r = b.submit("你好\n多行", {"C": [1, 2]}, ("S",))
        assert r.reply == "好的"
        assert r.writes == {"S": 5}
        entries = read_log(fake_pi)
        payload = [e for e in entries if e["kind"] == "pass_payload"][0]["data"]
        # 三键恒出现（§8.2）
        assert set(payload) == {"writable", "reads", "text"}
        assert payload["writable"] == ["S"]
        assert payload["reads"] == {"C": [1, 2]}
        assert payload["text"] == "你好\n多行"
        # 信令为单行紧凑 JSON（/pcl pass 前缀）
        prompt = [e for e in entries if e["kind"] == "prompt"][0]["data"]
        assert prompt.startswith("/pcl pass ")
        assert "\n" not in prompt
    finally:
        b.close()


def test_probe_missing_connector_a500(fake_pi):
    bin_ = fake_pi({"commands": [{"name": "other"}]})
    b = make_bridge(bin_)
    with pytest.raises(PclError, match="A500") as ei:
        b.start()
    assert "pcl-connector" in ei.value.message
    b.close()


def test_probe_duplicate_pcl_a500(fake_pi):
    bin_ = fake_pi({"commands": [{"name": "pcl:1"}, {"name": "pcl:2"}]})
    b = make_bridge(bin_)
    with pytest.raises(PclError, match="A500"):
        b.start()
    b.close()


def test_bad_pi_bin_a500(tmp_path):
    b = PiBridge(pi_bin=str(tmp_path / "nonexistent-pi"))
    with pytest.raises(PclError, match="A500"):
        b.start()


# ---- pass 时序（§8.2） ----------------------------------------------------------

def test_reply_fallback_from_event_cache(fake_pi):
    # get_last_assistant_text 为 null → 兜底缓存（message_end）仍可取（R2）
    bin_ = fake_pi({"reply_null": True,
                    "passes": [{"reply": "末条工具调用后的旧回复"}]})
    b = make_bridge(bin_)
    b.start()
    try:
        r = b.submit("p", {}, ())
        assert r.reply == "末条工具调用后的旧回复"
    finally:
        b.close()


def test_empty_reply_a504_via_runtime(fake_pi):
    bin_ = fake_pi({"passes": [{"reply": ""}]})
    b = make_bridge(bin_)
    b.start()
    try:
        with Run(bridge=b):
            with pytest.raises(PclError, match="A504"):
                rt_submit("p", {}, ())
    finally:
        b.close()


def test_r406_unauthorized_write(fake_pi):
    # write-only 未写文本 → 越权与空回复并存时 R406 优先（§7）
    bin_ = fake_pi({"passes": [{"reply": "", "writes": {"OTHER": 1}}]})
    b = make_bridge(bin_)
    b.start()
    try:
        with Run(bridge=b):
            with pytest.raises(PclError, match="R406"):
                rt_submit("p", {}, ())
    finally:
        b.close()


def test_extension_error_a501(fake_pi):
    bin_ = fake_pi({"passes": [{"reply": "x", "extension_error": "no model"}]})
    b = make_bridge(bin_)
    b.start()
    try:
        with pytest.raises(PclError, match="A501") as ei:
            b.submit("p", {}, ())
        assert "no model" in ei.value.message
    finally:
        b.close()


def test_other_extension_error_ignored(fake_pi):
    bin_ = fake_pi({"passes": [{"reply": "ok", "other_extension_error": True}]})
    b = make_bridge(bin_)
    b.start()
    try:
        r = b.submit("p", {}, ())
        assert r.reply == "ok"
    finally:
        b.close()


def test_response_error_a501(fake_pi):
    bin_ = fake_pi({"passes": [{"reply": "x", "never_settle": True,
                                "response_ok": False,
                                "response_error": "no api key"}]})
    b = make_bridge(bin_)
    b.start()
    try:
        with pytest.raises(PclError, match="A501") as ei:
            b.submit("p", {}, ())
        assert "no api key" in ei.value.message
    finally:
        b.close()


def test_timeout_a502_and_abort(fake_pi):
    bin_ = fake_pi({"passes": [{"reply": "x", "never_settle": True}]})
    b = make_bridge(bin_, timeout=0.4)  # 按次计（§8.2）
    b.start()
    try:
        with pytest.raises(PclError, match="A502"):
            b.submit("p", {}, ())
        # abort 已发出（写入与日志回落有微小延迟，短暂轮询）
        for _ in range(50):
            if "abort" in [e["kind"] for e in read_log(fake_pi)]:
                break
            time.sleep(0.02)
        kinds = [e["kind"] for e in read_log(fake_pi)]
        assert "abort" in kinds
    finally:
        b.close()


def test_exit_a503(fake_pi):
    bin_ = fake_pi({"passes": [{"reply": "x", "exit_after": True}]})
    b = make_bridge(bin_)
    b.start()
    try:
        with pytest.raises(PclError, match="A503"):
            b.submit("p", {}, ())
    finally:
        b.close()


def test_trace_receives_events(fake_pi):
    seen = []
    bin_ = fake_pi({"passes": [{"reply": "整段", "partial_delta": "增量",
                                "writes": {"S": 9}}]})
    b = PiBridge(pi_bin=bin_, timeout=5.0, trace=seen.append)
    b.start()
    try:
        b.submit("p", {}, ("S",))
        types = [e.get("type") for e in seen]
        assert "pcl_pass_submit" in types           # 合成：pass 提交
        assert "message_update" in types            # 流式事件（完整对象）
        assert "tool_execution_start" in types      # pcl_write 回流
        assert "agent_settled" in types             # 轮次边界
    finally:
        b.close()


def test_framing_crlf_and_u2028(fake_pi):
    # payload 含 U+2028 与换行：JSON 转义单行传输，对端无损还原
    weird = "第一 行\n第二 行"
    bin_ = fake_pi({"passes": [{"reply": "ok"}]})
    b = make_bridge(bin_)
    b.start()
    try:
        b.submit(weird, {}, ())
        payload = [e for e in read_log(fake_pi)
                   if e["kind"] == "pass_payload"][0]["data"]
        assert payload["text"] == weird
    finally:
        b.close()


def test_multiple_writes_last_wins(fake_pi):
    bin_ = fake_pi({"passes": [{"reply": "r", "writes": {"S": 1},
                                "writes_more": {"S": 9}}]})
    b = make_bridge(bin_)
    b.start()
    try:
        r = b.submit("p", {}, ("S",))
        assert r.writes == {"S": 9}   # 同名多次写，后者胜
    finally:
        b.close()


# ---- 上下文三指令（§8.3） --------------------------------------------------------

def test_save_names_and_refetches(fake_pi):
    fdir = fake_pi.log.parent / "fdir"
    bin_ = fake_pi({"rotate_on_name": str(fdir / "session-bbb.jsonl")})
    b = make_bridge(bin_)
    b.start()
    try:
        token = b.save()
        assert token == str(fake_pi.log.parent / "fdir" / "session-bbb.jsonl")   # 重取后的 sessionFile
        names = [e["data"] for e in read_log(fake_pi)
                 if e["kind"] == "set_session_name"]
        assert names == ["pcl:session-aaa"]              # pcl:<basename 去扩展名>
    finally:
        b.close()


def test_save_without_session_file_a501(fake_pi):
    bin_ = fake_pi({"state": {"sessionFile": None}})
    b = make_bridge(bin_)
    b.start()
    try:
        with pytest.raises(PclError, match="A501"):
            b.save()
    finally:
        b.close()


def test_load_precheck_missing_file_r430(fake_pi):
    bin_ = fake_pi({})
    b = make_bridge(bin_)
    b.start()
    try:
        with pytest.raises(PclError, match="R430"):
            b.load("/tmp/fake/never-written.jsonl")
        # 预检失败不应发 switch_session
        assert not [e for e in read_log(fake_pi)
                    if e["kind"] == "switch_session"]
    finally:
        b.close()


def test_load_ok_and_switch_fail(fake_pi, tmp_path):
    session = tmp_path / "s.jsonl"
    session.write_text("", encoding="utf-8")
    bin_ = fake_pi({})
    b = make_bridge(bin_)
    b.start()
    try:
        b.load(str(session))    # 文件存在 → 正常切换
        switched = [e for e in read_log(fake_pi) if e["kind"] == "switch_session"]
        assert switched == [{"kind": "switch_session", "data": str(session)}]
    finally:
        b.close()

    bin_ = fake_pi({"switch_fail": True})
    b = make_bridge(bin_)
    b.start()
    try:
        with pytest.raises(PclError, match="R430"):
            b.load(str(session))
    finally:
        b.close()


def test_load_cancelled_a501(fake_pi, tmp_path):
    session = tmp_path / "s.jsonl"
    session.write_text("", encoding="utf-8")
    bin_ = fake_pi({"switch_cancelled": True})
    b = make_bridge(bin_)
    b.start()
    try:
        with pytest.raises(PclError, match="A501"):
            b.load(str(session))
    finally:
        b.close()


def test_new_ctx(fake_pi):
    bin_ = fake_pi({})
    b = make_bridge(bin_)
    b.start()
    try:
        b.new_ctx()
        token = b.save()
        assert token == str(fake_pi.log.parent / "fdir" / "new-1.jsonl")
    finally:
        b.close()

    bin_ = fake_pi({"new_cancelled": True})
    b = make_bridge(bin_)
    b.start()
    try:
        with pytest.raises(PclError, match="A501"):
            b.new_ctx()
    finally:
        b.close()


# ---- 序列：save → new → load 往返（惰性落盘预检路径） ------------------------------

def test_context_roundtrip(fake_pi, tmp_path):
    # new 后的会话文件不存在于磁盘 → load 预检 R430（R20）；落盘后往返正常
    bin_ = fake_pi({})
    b = make_bridge(bin_)
    b.start()
    try:
        tok0 = b.save()
        Path(tok0).write_text("", encoding="utf-8")   # 模拟旧会话已落盘
        b.new_ctx()
        tok1 = b.save()
        assert tok1 != tok0
        with pytest.raises(PclError, match="R430"):
            b.load(tok1)                              # 未落盘 → 预检拦截
        Path(tok1).write_text("", encoding="utf-8")   # 模拟落盘
        b.load(tok1)
        b.load(tok0)                                  # 旧文件存在 → 正常切回
    finally:
        b.close()
