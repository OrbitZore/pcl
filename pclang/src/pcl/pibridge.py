"""pibridge — PiBridge：pi 子进程 + JSONL RPC 客户端 + 上下文管理（RFC 0001 §8）。

两种传输形态、单一协议（A13）：
- 正向（默认）：``pi --mode rpc [--name pcl-…] [-e <connector>]`` 子进程；
- 嵌入（``embed=True``，由 pi 内 ``/pcl run`` 拉起）：自身 stdio 为 RPC 通道
  （stdout 协议独占——CLI 侧把 sys.stdout 重定向到 stderr，§8.5）。

- 分帧：仅按 ``\\n`` 切分并剥离尾部 ``\\r``（JSON 串内合法含 U+2028/U+2029）；
- 就绪探测：``get_state`` → ``get_commands`` 验证 ``/pcl`` 已注册（缺失或
  重复注册 ``/pcl:N`` → A500，附安装/去重指引；嵌入形态由连接器合成应答）；
- pass 时序（§8.2）：每 pass 唯一信令 ``/pcl pass {三键恒出现}``；
  ``agent_settled`` 为唯一 pass 边界（M2 冒烟实测 pi@0.85.1：sendUserMessage
  为发后即忘、response ok 在预检通过时即发、早于 settled——状态机容忍任意
  次序，response 仅作屏障）；提交期错误经 ``extension_error`` 流出
  （``command:pcl`` = 连接器 handler 异常；``<runtime>``/``send_user_message``
  = sendUserMessage 抛错，如无模型/鉴权失败/compaction 进行中）→ A501；
  超时（按次）→ ``abort`` → A502；进程退出/管道 EOF → A503；坏帧 → A501；
- reply：``get_last_assistant_text`` 为主、``message_end``/``turn_end`` 事件
  缓存兜底（每 pass 重置，R2）；
- pcl_write 写值随 ``tool_execution_start`` 事件回流（``values`` 包装解包）；
- 上下文（§8.3）：token = ``get_state`` 的 ``sessionFile``；``:save`` 先命名
  ``pcl:<basename>`` 再重取（嵌入形态跳过命名）；``:load`` 本地文件存在性
  预检 → R430；嵌入形态的会话替换类操作由连接器按 §8.6 以 ``reason`` 拒绝
  （``embed-ctx-unsupported`` → A520、``embed-orphaned`` → A521、
  ``embed-cross-cwd`` → A522、``embed-no-session-control`` → A523）；
- 生命周期（§8.4）：正向 close stdin → 等待 → SIGTERM → SIGKILL，stderr 尾部
  并入 A500/A503 诊断；嵌入形态 stdin EOF → A503（宿主退出，§8.6）。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time

from .bridge import IAgentBridge, PassResult
from .errors import PclError

_PCL_CMD_RE = re.compile(r"pcl(:\d+)?")

# 嵌入形态失败 reason → 错误码（§8.6 失败语义；协议零新命令，仅 reason 成文）
_EMBED_REASON_CODES = {
    "embed-ctx-unsupported": "A520",
    "embed-orphaned": "A521",
    "embed-cross-cwd": "A522",
    "embed-no-session-control": "A523",
}

# pi@0.85.1：response ok 严格晚于 settled 的预设不成立（sendUserMessage 发后
# 即忘）——settled 后响应屏障的额外宽限
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


# ---- 传输层 ---------------------------------------------------------------

class _Transport:
    """RPC 通道抽象：发帧、收帧回调、退出信号。"""

    def __init__(self, on_frame, on_eof, on_protocol_error):
        self._on_frame = on_frame
        self._on_eof = on_eof
        self._on_protocol_error = on_protocol_error
        self.exited = False
        self.exit_code: int | None = None
        self.stderr_tail: list[str] = []

    def send_line(self, line: str):
        raise NotImplementedError

    def start(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    def _pump(self, read_chunk):
        """循环取块 → 按 \\n 切分并剥尾部 \\r → 逐帧回调；EOF 后标记退出。"""
        buf = b""
        try:
            while True:
                try:
                    chunk = read_chunk()
                except Exception:
                    break
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
                    try:
                        obj = json.loads(line.decode("utf-8", "replace"))
                    except ValueError:
                        self._on_protocol_error(
                            ("A501", f"JSONL 帧解析失败：{line[:160]!r}"))
                        continue
                    self._on_frame(obj)
        except Exception:
            pass
        finally:
            self._mark_eof()
            self._on_eof()

    def _mark_eof(self):
        raise NotImplementedError


class _SubprocessTransport(_Transport):
    """正向形态：pi 子进程管道。"""

    def __init__(self, cmd: list[str], **kw):
        super().__init__(**kw)
        try:
            self.proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
        except OSError as e:
            raise PclError("A500", f"无法启动 pi（{cmd[0]!r}）：{e}") from None
        self._reader = threading.Thread(target=self._pump, args=(self._read_chunk,),
                                        daemon=True)
        self._stderr_reader = threading.Thread(target=self._drain_stderr,
                                               daemon=True)

    def start(self):
        self._reader.start()
        self._stderr_reader.start()

    def _read_chunk(self):
        return self.proc.stdout.read1(1 << 16)   # 读到即返（read 会等满 buffer）

    def send_line(self, line: str):
        data = (line + "\n").encode("utf-8")
        try:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise PclError("A503", f"向 pi 写入失败（进程已退出？）：{e}") from None

    def close(self):
        proc = getattr(self, "proc", None)
        if proc is None:
            return
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
        for t in (getattr(self, "_reader", None),
                  getattr(self, "_stderr_reader", None)):
            if t is not None:
                t.join(timeout=2)

    def _drain_stderr(self):
        try:
            for raw in iter(self.proc.stderr.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip("\n")
                self.stderr_tail.append(line)
                if len(self.stderr_tail) > 1000:
                    del self.stderr_tail[:500]
        except Exception:
            pass

    def _mark_eof(self):
        self.exited = True
        self.exit_code = self.proc.poll()


class _StdioTransport(_Transport):
    """嵌入形态：自身 stdio 为 RPC 通道（stdout 让给协议，§8.5）。"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self._out = sys.__stdout__     # 真实 stdout（CLI 已把 sys.stdout 重定向到 stderr）
        self._reader = threading.Thread(target=self._pump, args=(self._read_chunk,),
                                        daemon=True)

    def start(self):
        self._reader.start()

    def _read_chunk(self):
        # 经 select+os.read 直读 fd：不触碰 sys.stdin 的 BufferedReader
        # （持有其锁的阻塞线程会导致解释器关闭时致命错误——实测 SIGABRT）
        import select
        fd = sys.stdin.fileno()
        while True:
            r, _, _ = select.select([fd], [], [], 0.25)
            if r:
                return os.read(fd, 1 << 16)
            # 超时空转：daemon 线程随进程退出，无需可中断唤醒

    def send_line(self, line: str):
        data = (line + "\n").encode("utf-8")
        try:
            self._out.buffer.write(data)
            self._out.buffer.flush()
        except (BrokenPipeError, OSError, ValueError) as e:
            raise PclError("A503", f"向宿主写入失败（管道已断？）：{e}") from None

    def close(self):
        pass   # 嵌入形态：无子进程可清理；宿主经 stdin EOF 通知退出（→ A503）

    def _mark_eof(self):
        self.exited = True
        self.exit_code = None


class PiBridge(IAgentBridge):
    def __init__(self, *, pi_bin: str = "pi", connector_path: str | None = None,
                 pi_args: list | None = None, timeout: float = 300.0,
                 trace=None, name: str | None = None, embed: bool = False):
        self.pi_bin = pi_bin or "pi"
        self.connector_path = connector_path or "none"
        self.pi_args = [str(a) for a in (pi_args or [])]
        self.timeout = float(timeout) if timeout else 300.0
        self.trace = trace              # callable(delta: str) | None
        self.name = name
        self.embed = embed

        self._transport: _Transport | None = None
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._responses: dict = {}
        self._seq = 0
        self._protocol_error: tuple[str, str] | None = None
        self._closed = False
        # pass 进行时状态
        self._pass_writes: dict = {}
        self._reply_cache = ""
        self._settled_seq = 0
        self._pass_error: tuple[str, str] | None = None

    # ---- 生命周期 ---------------------------------------------------------

    def start(self):
        kw = dict(on_frame=self._handle_frame,
                  on_eof=self._on_eof,
                  on_protocol_error=self._on_protocol_error)
        if self.embed:
            self._transport = _StdioTransport(**kw)
        else:
            cmd = [self.pi_bin, "--mode", "rpc",
                   "--name", self.name or f"pcl-{os.getpid()}-{int(time.time())}"]
            if self.connector_path and self.connector_path != "none":
                cmd += ["-e", str(self.connector_path)]
            cmd += self.pi_args
            self._transport = _SubprocessTransport(cmd, **kw)
        self._transport.start()
        self._probe_ready()

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._cond.notify_all()
        if self._transport is not None:
            self._transport.close()

    def context(self, text: str) -> None:
        """上下文注入：forward 经 steer（独立用户消息排队）；embed 经 context 命令。"""
        if self.embed:
            self._call({"type": "context", "text": text})
        else:
            self._send({"type": "steer", "message": text})

    def note(self, text: str) -> bool:
        """嵌入形态：注记经 note 命令下发（连接器 appendEntry 进会话流）；
        正向形态返回 False（回落输出文档）。"""
        if not self.embed:
            return False
        self._call({"type": "note", "text": text})
        return True

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
                "  ① pi install <repo>/pcl-connector/pi（pi 包；或发布后 "
                "npm:pcl-connector-pi / git 源）；\n"
                "  ② 运行时用 --connector-path 直指 pcl-connector/pi"
                "（包目录或 extensions/index.ts 文件）")
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
        if self.trace is not None:
            try:
                self.trace({"type": "pcl_pass_submit", "chars": len(prompt)})
            except Exception:
                pass
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
                    # response ok 仅作屏障（§8.2/RFC 0001 §16）：settled 才是边界
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._cond.wait(min(remaining, 0.25))

        if not settled:
            self.abort()   # 超时：发 abort 后 A502（按次计，§8.2）
            raise PclError(
                "A502",
                f"等待 agent 空闲超时（{self.timeout:.0f}s，按次计）；已发送 abort")

        # 响应屏障：settled 后短暂等待 response（任意次序均容忍）
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

    # ---- 上下文三指令（§8.3/§8.6） ---------------------------------------------

    def save(self) -> str:
        sf = self._session_file(self._call({"type": "get_state"}))
        if not sf:
            raise PclError(
                "A501", "当前会话无 sessionFile（--no-session / 宿主会话未落盘），"
                        ":save 无可用 token（宁报错不返回空值）")
        if not self.embed:
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
            raise self._context_failure(resp,
                                        lambda e: PclError(
                                            "R430", f"switch_session 失败：{e}"))

    def new_ctx(self) -> None:
        resp = self._call({"type": "new_session"})
        if (resp.get("data") or {}).get("cancelled"):
            raise PclError("A501", "new_session 被扩展事件取消")
        if not resp.get("success"):
            raise self._context_failure(
                resp, lambda e: PclError("A501", f"new_session 失败：{e}"))

    @staticmethod
    def _context_failure(resp: dict, fallback):
        """上下文操作失败：嵌入 reason → A52x（§8.6）；否则按正向语义兜底。"""
        reason = (resp.get("data") or {}).get("reason")
        code = _EMBED_REASON_CODES.get(str(reason))
        if code:
            hint = {
                "A520": "（嵌入形态的会话替换接续属 M4；请改用正向 CLI）",
                "A521": "（接续窗口内无新实例接管——跨 cwd/reload）",
                "A522": "（:load 目标 cwd ≠ 当前，请走正向 CLI）",
                "A523": "（会话切换后绑定降级；执行任一 /pcl 命令恢复或改用正向 CLI）",
            }[code]
            return PclError(code, f"嵌入模式上下文操作被拒（reason={reason}）{hint}")
        return fallback(resp.get("error"))

    @staticmethod
    def _session_file(resp: dict):
        sf = (resp.get("data") or {}).get("sessionFile")
        return sf if isinstance(sf, str) and sf else None

    # ---- RPC 底座 -----------------------------------------------------------

    def _send(self, obj: dict):
        assert self._transport is not None
        self._transport.send_line(
            json.dumps(obj, ensure_ascii=False, separators=(",", ":")))

    def _call(self, cmd: dict, timeout: float | None = None) -> dict:
        """请求-响应 RPC（等待对端 response）。"""
        limit = timeout if timeout is not None else self.timeout
        with self._lock:
            if self._protocol_error:
                raise PclError(*self._protocol_error)
            self._seq += 1
            cid = self._seq
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
        transport = self._transport
        if transport is not None and transport.exited:
            tail = ""
            if transport.stderr_tail:
                joined = "\n".join(
                    transport.stderr_tail[-_STDERR_TAIL_LINES:])
                tail = f"；stderr 尾部：\n{joined}"
            raise PclError(
                "A503",
                f"pi{' 宿主' if self.embed else ' 子进程'}已退出"
                f"（code={transport.exit_code}）{tail}")

    # ---- 帧处理（读线程回调） ---------------------------------------------------

    def _on_eof(self):
        with self._cond:
            self._cond.notify_all()

    def _on_protocol_error(self, err):
        with self._cond:
            self._protocol_error = err
            self._cond.notify_all()

    def _handle_frame(self, obj: dict):
        ftype = obj.get("type")
        if ftype == "response":
            with self._cond:
                self._responses[obj.get("id")] = obj
                self._cond.notify_all()
        elif ftype == "extension_error":
            path = str(obj.get("extensionPath") or "")
            event = str(obj.get("event") or "")
            # command:pcl = 连接器 handler 异常；<runtime>/send_user_message =
            # sendUserMessage 抛错（无模型/鉴权失败/compaction 进行中，§8.2）
            if path.startswith("command:pcl") or event == "send_user_message":
                with self._cond:
                    self._pass_error = (
                        "A501", f"pass 提交期错误（{path or event}）：{obj.get('error')}")
                    self._cond.notify_all()
        elif ftype == "agent_settled":
            if self.trace is not None:
                try:
                    self.trace(obj)
                except Exception:
                    pass
            with self._cond:
                self._settled_seq += 1
                self._cond.notify_all()
        elif ftype == "tool_execution_start":
            if obj.get("toolName") == "pcl_write":
                args = obj.get("args")
                if isinstance(args, dict):
                    # 连接器工具契约：参数经命名键 values 承载（pi@0.85.1 实测
                    # 顶层开放形状会被校验层剥空）；严格 schema 下外层恒为包装，
                    # 解包无歧义（平铺形态仅作兜底）
                    inner = args.get("values")
                    if isinstance(inner, dict) and set(args) == {"values"}:
                        args = inner
                    if self.trace is not None:
                        try:
                            self.trace(obj)
                        except Exception:
                            pass
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
                try:
                    self.trace(obj)      # 完整事件（格式化器自取增量）
                except Exception:
                    pass
        # 其余事件（extension_ui_request 等）：记录/忽略
