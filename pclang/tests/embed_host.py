#!/usr/bin/env python3
"""伪嵌入宿主（测试设施）：扮演连接器侧，经 stdio JSONL 驱动 pcl --agent embed。

用法：fake_embed_host.py <pcl_bin> <out_path> <cfg_json>
cfg：{file, prompt?, passes?, sessionFile?, new_reason?, switch_reason?}
输出（stdout，供测试解析）：EXIT: <code> / STDERR: <尾部> / OUT-EXISTS: <bool>
"""

import json
import os
import subprocess
import sys
import threading
import time

pcl_bin, out_path, script_cfg = sys.argv[1], sys.argv[2], sys.argv[3]
cfg = json.loads(open(script_cfg, encoding="utf-8").read())
passes = list(cfg.get("passes", []))
last_reply = None
state = {"sessionFile": cfg.get("sessionFile", "/tmp/fake-embed-session.jsonl")}

p = subprocess.Popen(
    [pcl_bin, "run", cfg["file"], cfg.get("prompt", ""),
     "--agent", "embed", "-o", out_path, "--cache", "none"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

frames = []


def reader():
    buf = b""
    while True:
        chunk = p.stdout.read1(65536)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if line.endswith(b"\r"):
                line = line[:-1]
            frames.append(line.decode("utf-8", "replace"))


threading.Thread(target=reader, daemon=True).start()


def send(obj):
    p.stdin.write((json.dumps(obj, ensure_ascii=False) + "\n").encode())
    p.stdin.flush()


def resp(cid, command, ok=True, data=None, error=None):
    r = {"id": cid, "type": "response", "command": command, "success": ok}
    if data is not None:
        r["data"] = data
    if error:
        r["error"] = error
    send(r)


def next_cmd(timeout=15):
    n0 = len(frames)
    deadline = time.time() + timeout
    while time.time() < deadline:
        for f in frames[n0:]:
            try:
                return json.loads(f)
            except ValueError:
                pass
        time.sleep(0.05)
    return None


while True:
    c = next_cmd()
    if c is None:
        break
    t, cid = c.get("type"), c.get("id")
    if t == "get_state":
        resp(cid, "get_state", data=dict(state))
    elif t == "get_commands":
        resp(cid, "get_commands",
             data={"commands": [{"name": "pcl", "source": "extension"}]})
    elif t == "set_session_name":
        resp(cid, "set_session_name")
    elif t == "get_last_assistant_text":
        resp(cid, "get_last_assistant_text", data={"text": last_reply})
    elif t == "prompt":
        ps = passes.pop(0) if passes else {}
        for k, v in (ps.get("writes") or {}).items():
            send({"type": "tool_execution_start", "toolCallId": "c1",
                  "toolName": "pcl_write", "args": {"values": {k: v}}})
        last_reply = ps.get("reply", "ok")
        if not ps.get("never_settle"):
            send({"type": "agent_settled"})
        resp(cid, "prompt")
    elif t == "new_session":
        reason = cfg.get("new_reason", "embed-ctx-unsupported")
        resp(cid, "new_session", ok=False, data={"reason": reason})
    elif t == "switch_session":
        reason = cfg.get("switch_reason", "embed-ctx-unsupported")
        resp(cid, "switch_session", ok=False, data={"reason": reason})
    else:
        resp(cid, t, ok=False, error="unknown")

try:
    rc = p.wait(timeout=10)
except subprocess.TimeoutExpired:
    p.kill()
    rc = p.poll()
err = p.stderr.read().decode("utf-8", "replace")
print("EXIT:", rc)
if err.strip():
    print("STDERR:", err[-2000:])
print("OUT-EXISTS:", os.path.exists(out_path))
