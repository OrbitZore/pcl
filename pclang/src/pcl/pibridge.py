"""pibridge — PiBridge：pi 子进程 + JSONL RPC 客户端 + 上下文管理（DESIGN §8）。

- 子进程：``pi --mode rpc [--name pcl-…] [-e <connector>] [*pi_args]``（§8.1）；
- 分帧：自维护 buffer，仅按 ``\\n`` 切分并剥离尾部 ``\\r``（JSON 串内合法含
  U+2028/U+2029，禁用通用行分割语义）；
- 就绪探测：``get_state`` → ``get_commands`` 验证 ``/pcl`` 已注册（缺失或
  重复注册 ``/pcl:N`` → A500，附安装/去重指引）；
- 读线程分派：``response``（按 id）/ ``tool_execution_start``（pcl_write 写值回流）/
  ``message_update``（--trace 流式）/ ``message_end``/``turn_end``（末条 assistant
  text 兜底缓存，每 pass 重置）/ ``agent_settled``（pass 边界）/
  ``extension_error``（在途 pass 且 command:pcl → A501）；
- pass 时序（§8.2）：每 pass 唯一信令 ``/pcl pass {三键恒出现}``；settled 是唯一
  pass 边界（M2 冒烟实测 pi@0.85.1：pi.sendUserMessage 为发后即忘，response ok
  在预检通过时即发、早于 settled；状态机容忍任意次序，response 仅作屏障）；
  超时（按次）→ ``abort`` → A502；子进程退出 → A503；坏帧 → A501；
- 上下文（§8.3）：token = ``get_state`` 的 ``sessionFile`` 绝对路径；``:save``
  先命名 ``pcl:<basename>`` 再重取；``:load`` 本地文件存在性预检 → R430；
- 生命周期（§8.4）：close stdin → 等待 → SIGTERM → SIGKILL；stderr 尾部并入
  A500/A503 诊断。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time

from .bridge import IAgentBridge, PassResult
from .errors import PclError

_PCL_CMD_RE = re.compile(r"pcl(:\d+)?")

# pi@0.85.1：response ok 严格晚于 agent_settled——settled 后响应屏障的额外宽限
_BARRIER_GRACE = 10.0

_STDERR_TAIL_LINES = 40


def _assistant_text(msg: dict) -> str:
    """AssistantMessage → 文本内容（text 块拼接）。"""
    content = msg.get("content")
    if isinstance(content, str):
        return content
    parts = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" \
                    and isinstance(block.get("text"), str):
                parts.append(block["text"])
    return "".join(parts)


class PiBridge(IAgentBridge):
    def __init__(self, *, pi_bin: str = "pi", connector_path: str | None = None,
                 pi_args: list | None = None, timeout: float = 300.0,
                 trace=None, name: str | None = None):
        self.pi_bin = pi_bin or "pi"
        self.connector_path = connector_path or "none"
        self.pi_args = [str(a) for a in (pi_args or [])]
        self.timeout = float(timeout) if timeout else 300.0
        self.trace = trace              # callable(delta: str) | None
        self.name = name

        self.proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._responses: dict = {}
        self._seq = 0
        self._exited = False
        self._exit_code: int | None = None
        self._protocol_error: tuple[str, str] | None = None
        self._stderr_tail: list[str] = []
        self._closed = False
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        # pass 进行时状态
        self._pass_writes: dict = {}
        self._reply_cache = ""
        self._settled_seq = 0
        self._pass_error: tuple[str, str] | None = None

    # ---- 生命周期 ---------------------------------------------------------

    def start(self):
        cmd = [self.pi_bin, "--mode", "rpc",
               "--name", self.name or f"pcl-{os.getpid()}-{int(time.time())}"]
        if self.connector_path and self.connector_path != "none":
            cmd += ["-e", str(self.connector_path)]
        cmd += self.pi_args
        try:
            self.proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
        except OSError as e:
            raise PclError("A500", f"无法启动 pi（{self.pi_bin!r}）：{e}") from None
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._reader.start()
        self._stderr_reader.start()
        self._probe_ready()

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._cond.notify_all()
        proc = self.proc
        if proc is None:
            return
        # 先关 stdin → pi 读线程 EOF 自然退出（§8.4）；宽限后 SIGTERM/SIGKILL 兜底
        try:
            if proc.stdin and not proc.stdin.closed:
                try:
                    proc.stdin.close()
                except OSError:
                    pass
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
        for stream in (proc.stdout, proc.stderr):
            try:
                if stream is not None and not stream.closed:
                    stream.close()
            except OSError:
                pass
        for t in (self._reader, self._stderr_reader):
            if t is not None:
                t.join(timeout=2)

    def abort(self):
        try:
            self._send({"type": "abort"})
        except PclError:
            pass

    # ---- 就绪探测（§8.1） ---------------------------------------------------

    def _probe_ready(self):
        self._call({"type": "get_state"})
        resp = self._call({"type": "get_commands"})
        commands = ((resp.get("data") or {}).get("commands")) or []
        names = [c.get("name") for c in commands if isinstance(c, dict)]
        pcl_entries = [n for n in names
                       if isinstance(n, str) and _PCL_CMD_RE.fullmatch(n)]
        if not pcl_entries:
            raise PclError(
                "A500",
                "未检测到 pcl-connector（/pcl 命令未注册）。安装方式二选一：\n"
                "  ① 复制/链接本仓 pcl-connector/index.ts 到 pi 扩展目录"
                "（~/.pi/agent/extensions/）；\n"
                "  ② 运行时用 --connector-path 直指 index.ts 源文件")
        if len(pcl_entries) > 1 or pcl_entries[0] != "pcl":
            raise PclError(
                "A500",
                f"pcl-connector 被重复注册（{', '.join('/' + n for n in pcl_entries)}），"
                "信令分发目标不确定。请只保留一处注册"
                "（预装与 --connector-path 并存会得到 /pcl:1、/pcl:2）")

    # ---- submit（§8.2） -----------------------------------------------------

    def submit(self, prompt: str, reads: dict, writes: tuple[str, ...]) -> PassResult:
        allowed = tuple(writes)
        payload = {"writable": list(allowed), "reads": reads or {}, "text": prompt}
        message = "/pcl pass " + json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._pass_writes = {}
            self._reply_cache = ""
            self._pass_error = None
            settled_before = self._settled_seq
            self._seq += 1
            pass_id = self._seq
        self._send({"id": pass_id, "type": "prompt", "message": message})
        deadline = time.monotonic() + self.timeout

        settled = False
        with self._cond:
            while True:
                self._check_failures_locked()
                if self._settled_seq > settled_before:
                    settled = True
                    break
                resp = self._responses.get(pass_id)
                if resp is not None:
                    if not resp.get("success"):
                        raise PclError(
                            "A501", f"pass 提交失败：{resp.get('error')}")
                    # M2 冒烟实测（pi@0.85.1）：pi.sendUserMessage 为发后即忘，
                    # response ok 在预检通过时即发出——早于 agent_settled。
                    # settled 是唯一 pass 边界，response 仅作屏障（容忍任意次序）。
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._cond.wait(min(remaining, 0.25))

        if not settled:
            self.abort()   # 超时：发 abort 后 A502（按次计，§8.2）
            raise PclError(
                "A502",
                f"等待 agent 空闲超时（{self.timeout:.0f}s，按次计）；已发送 abort")

        # 响应屏障：settled 后短暂等待 response（源码已核严格晚于 settled，§8.2）
        resp = None
        barrier_deadline = time.monotonic() + min(_BARRIER_GRACE, self.timeout)
        with self._cond:
            while True:
                self._check_failures_locked()
                resp = self._responses.pop(pass_id, None)
                if resp is not None:
                    break
                remaining = barrier_deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._cond.wait(min(remaining, 0.25))
        if resp is None or not resp.get("success"):
            # 已 settled：response 缺失/失败均视为协议错
            raise PclError("A501",
                           f"pass 响应异常：{resp.get('error') if resp else '未到达'}")

        # reply：get_last_assistant_text 为主、事件缓存兜底（§8.2/R2）
        reply = ""
        try:
            r = self._call({"type": "get_last_assistant_text"})
            text = (r.get("data") or {}).get("text")
            if isinstance(text, str) and text:
                reply = text
        except PclError as e:
            if e.code not in ("A502",):
                raise
        if not reply:
            with self._lock:
                reply = self._reply_cache
        with self._lock:
            writes_seen = dict(self._pass_writes)
        return PassResult(reply, writes_seen)

    # ---- 上下文三指令（§8.3） -------------------------------------------------

    def save(self) -> str:
        sf = self._session_file(self._call({"type": "get_state"}))
        if not sf:
            raise PclError(
                "A501", "当前会话无 sessionFile（--no-session / 宿主会话未落盘），"
                        ":save 无可用 token（宁报错不返回空值）")
        base = os.path.basename(sf)
        stem = base.rsplit(".", 1)[0] if "." in base else base
        try:
            # 仅为 /resume 辨识命名；失败不致命（token 仍有效）
            self._call({"type": "set_session_name", "name": f"pcl:{stem}"})
        except PclError:
            pass
        # 改名可能轮转会话文件 → 重取，以末次 sessionFile 为 token（§8.3/R14）
        sf2 = self._session_file(self._call({"type": "get_state"}))
        if not sf2:
            raise PclError("A501", ":save 重取状态时无 sessionFile")
        return str(sf2)

    def load(self, token: str) -> None:
        # 本地预检：pi 惰性落盘（首个 assistant 回复后才写盘，R20）——
        # 缺失文件若交由 pi 兜底会静默丢上下文，显式拦为 R430
        if not os.path.isfile(token):
            raise PclError(
                "R430", f"token 文件不存在（会话未落盘？）：{token}")
        resp = self._call({"type": "switch_session", "sessionPath": token})
        if (resp.get("data") or {}).get("cancelled"):
            raise PclError("A501", "switch_session 被扩展事件取消")
        if not resp.get("success"):
            raise PclError("R430",
                           f"switch_session 失败：{resp.get('error')}")

    def new_ctx(self) -> None:
        resp = self._call({"type": "new_session"})
        if (resp.get("data") or {}).get("cancelled"):
            raise PclError("A501", "new_session 被扩展事件取消")
        if not resp.get("success"):
            raise PclError("A501",
                           f"new_session 失败：{resp.get('error')}")

    @staticmethod
    def _session_file(resp: dict):
        sf = (resp.get("data") or {}).get("sessionFile")
        return sf if isinstance(sf, str) and sf else None

    # ---- RPC 底座 -----------------------------------------------------------

    def _next_id_locked(self):
        self._seq += 1
        return self._seq

    def _send(self, obj: dict):
        assert self.proc is not None and self.proc.stdin is not None
        line = json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"
        try:
            self.proc.stdin.write(line.encode("utf-8"))
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise PclError("A503", f"向 pi 写入失败（进程已退出？）：{e}") from None

    def _call(self, cmd: dict, timeout: float | None = None) -> dict:
        """请求-响应 RPC（等待对端 response）。"""
        limit = timeout if timeout is not None else self.timeout
        with self._lock:
            if self._protocol_error:
                raise PclError(*self._protocol_error)
            cid = self._next_id_locked()
        self._send({"id": cid, **cmd})
        deadline = time.monotonic() + limit
        with self._cond:
            while True:
                self._check_failures_locked()
                resp = self._responses.get(cid)
                if resp is not None:
                    del self._responses[cid]
                    return resp
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PclError("A502",
                                   f"RPC {cmd.get('type')} 等待响应超时（{limit:.0f}s）")
                self._cond.wait(min(remaining, 0.25))

    def _check_failures_locked(self):
        if self._pass_error:
            raise PclError(*self._pass_error)
        if self._protocol_error:
            raise PclError(*self._protocol_error)
        if self._exited:
            tail = ""
            if self._stderr_tail:
                joined = "\n".join(self._stderr_tail[-_STDERR_TAIL_LINES:])
                tail = f"；stderr 尾部：\n{joined}"
            raise PclError(
                "A503",
                f"pi 子进程已退出（code={self._exit_code}）{tail}")

    # ---- 读线程 -------------------------------------------------------------

    def _read_stdout(self):
        stream = self.proc.stdout
        buf = b""
        assert stream is not None
        try:
            while True:
                chunk = stream.read1(1 << 16)   # 读到即返（read 会等满 buffer）
                if not chunk:
                    break
                buf += chunk
                while True:
                    nl = buf.find(b"\n")
                    if nl == -1:
                        break
                    line = buf[:nl]
                    buf = buf[nl + 1:]
                    if line.endswith(b"\r"):
                        line = line[:-1]
                    self._handle_frame(line.decode("utf-8", "replace"))
        except Exception:
            pass
        finally:
            with self._cond:
                self._exited = True
                if self.proc is not None:
                    self._exit_code = self.proc.poll()
                self._cond.notify_all()

    def _read_stderr(self):
        stream = self.proc.stderr
        assert stream is not None
        try:
            for raw in iter(stream.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip("\n")
                with self._lock:
                    self._stderr_tail.append(line)
                    if len(self._stderr_tail) > 1000:
                        del self._stderr_tail[:500]
        except Exception:
            pass

    def _handle_frame(self, line: str):
        try:
            obj = json.loads(line)
        except ValueError:
            with self._cond:
                self._protocol_error = ("A501", f"JSONL 帧解析失败：{line[:160]!r}")
                self._cond.notify_all()
            return
        ftype = obj.get("type")
        if ftype == "response":
            with self._cond:
                self._responses[obj.get("id")] = obj
                self._cond.notify_all()
        elif ftype == "extension_error":
            path = str(obj.get("extensionPath") or "")
            if path.startswith("command:pcl"):
                with self._cond:
                    self._pass_error = (
                        "A501", f"连接器 handler 异常（{path}）：{obj.get('error')}")
                    self._cond.notify_all()
        elif ftype == "agent_settled":
            with self._cond:
                self._settled_seq += 1
                self._cond.notify_all()
        elif ftype == "tool_execution_start":
            if obj.get("toolName") == "pcl_write":
                args = obj.get("args")
                if isinstance(args, dict):
                    # 连接器工具契约：参数经命名键 values 承载（pi@0.85.1 实测
                    # 顶层开放形状会被校验层剥空）；严格 schema 下外层恒为包装，
                    # 解包无歧义（平铺形态仅作兑底）
                    inner = args.get("values")
                    if isinstance(inner, dict) and set(args) == {"values"}:
                        args = inner
                    with self._cond:
                        self._pass_writes.update(args)
        elif ftype in ("message_end", "turn_end"):
            msg = obj.get("message") or {}
            if msg.get("role") == "assistant":
                text = _assistant_text(msg)
                if text:
                    with self._cond:
                        self._reply_cache = text
        elif ftype == "message_update":
            if self.trace is not None:
                ev = obj.get("assistantMessageEvent") or {}
                if ev.get("type") == "text_delta" and ev.get("delta"):
                    try:
                        self.trace(ev["delta"])
                    except Exception:
                        pass
        # 其余事件（extension_ui_request 等）：记录/忽略
