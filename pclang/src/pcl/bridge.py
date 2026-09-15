"""bridge — IAgentBridge 抽象与 Null / Script 测试桥（DESIGN §7）。

PiBridge（pi 适配）属 M2，另行交付；embed 传输属 M3。
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path

from .errors import PclError


class PassResult:
    """一轮 pass 的结果：reply 文本 + agent 写回的名字→值映射。"""

    __slots__ = ("reply", "writes")

    def __init__(self, reply: str = "", writes: dict | None = None):
        self.reply = reply
        self.writes = writes or {}


class IAgentBridge(ABC):
    """桥接层接口：submit / 上下文三指令 / 生命周期。"""

    def start(self) -> None:  # Run.__enter__ 调用
        pass

    def close(self) -> None:
        pass

    @abstractmethod
    def submit(self, prompt: str, reads: dict, writes: tuple[str, ...]) -> PassResult:
        """提交 prompt（已 trim、非空），阻塞至 agent 空闲。"""

    @abstractmethod
    def save(self) -> str:
        """返回当前上下文 token（opaque str）。"""

    @abstractmethod
    def load(self, token: str) -> None:
        """切换上下文；token 未知/失效 → R430。"""

    @abstractmethod
    def new_ctx(self) -> None:
        """新建匿名上下文并切换。"""

    def abort(self) -> None:
        pass


class NullBridge(IAgentBridge):
    """``--agent null``：reply = prompt 原文、writes 为空；token 合成自增。"""

    def __init__(self):
        self._tokens: set[str] = set()
        self._seq = 0

    def _mint(self) -> str:
        self._seq += 1
        tok = f"null-{self._seq}"
        self._tokens.add(tok)
        return tok

    def submit(self, prompt, reads, writes):
        return PassResult(prompt, {})

    def save(self) -> str:
        return self._mint()

    def load(self, token: str) -> None:
        if token not in self._tokens:
            raise PclError("R430", f"未知的上下文 token：{token!r}")

    def new_ctx(self) -> None:
        self._mint()


class ScriptBridge(IAgentBridge):
    """``--agent script --script f.jsonl``：按序回放 {reply, writes}。

    - 回放耗尽 → A510（含已消费/总条数）；
    - 空 prompt 跳过不调桥（runtime.submit 内处理），不消耗条目；
    - 上下文 token 合成自增（save/load 可回放）。
    """

    def __init__(self, script: str | Path):
        self.script_path = Path(script)
        self.entries: list[dict] = []
        self._idx = 0
        self._tokens: set[str] = set()
        self._seq = 0

    def start(self):
        try:
            text = self.script_path.read_text(encoding="utf-8")
        except OSError as e:
            raise PclError("A500", f"无法读取 script 文件：{e}") from None
        self.entries = []
        for ln, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise PclError("A500",
                               f"script 第 {ln} 行不是合法 JSON：{e}") from None
            self.entries.append(obj)

    def submit(self, prompt, reads, writes):
        if self._idx >= len(self.entries):
            raise PclError(
                "A510",
                f"script 桥回放耗尽（已消费 {self._idx}/{len(self.entries)} 条）")
        e = self.entries[self._idx]
        self._idx += 1
        return PassResult(e.get("reply", ""), e.get("writes") or {})

    def _mint(self) -> str:
        self._seq += 1
        tok = f"script-{self._seq}"
        self._tokens.add(tok)
        return tok

    def save(self) -> str:
        return self._mint()

    def load(self, token: str) -> None:
        if token not in self._tokens:
            raise PclError("R430", f"未知的上下文 token：{token!r}")

    def new_ctx(self) -> None:
        self._mint()


def make_bridge(agent: str, *, script: str | Path | None = None,
                pi_bin: str | None = None, connector_path: str | None = None,
                pi_args: list | None = None, timeout: float | None = None,
                trace=None, **_kw) -> IAgentBridge:
    """按 --agent 构造桥。embed（嵌入模式）属 M3 交付。"""
    if agent == "null":
        return NullBridge()
    if agent == "script":
        if not script:
            raise PclError("A500", "--agent script 需要 --script PATH")
        return ScriptBridge(script)
    if agent == "pi":
        from .pibridge import PiBridge
        tracer = None
        if trace:
            import sys
            tracer = lambda d: sys.stderr.write(d)  # noqa: E731
        return PiBridge(pi_bin=pi_bin or "pi", connector_path=connector_path,
                        pi_args=pi_args, timeout=timeout or 300.0, trace=tracer)
    if agent == "embed":
        raise NotImplementedError(
            "嵌入模式（--agent embed，由 pi 内 /pcl run 拉起）属 M3 里程碑，尚未交付")
    raise NotImplementedError(f"未知 agent：{agent!r}")
