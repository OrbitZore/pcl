"""smoke-pi（嵌入形态）：真 pi 会话内 /pcl 命令族（DESIGN §8.5/§9.1）。

经 RPC `prompt` 分发扩展命令（与 TUI 敲 /pcl 等价）。多数用例不需要模型：
gen/version 直通、:save（合成 get_state）、:new → A520、正向专属选项拒绝。
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from pcl.pibridge import PiBridge

CONNECTOR = Path(__file__).resolve().parent.parent.parent / "pcl-connector" / "index.ts"
PCL_BIN = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "pcl"
DATA = Path(__file__).resolve().parent / "data"

pytestmark = pytest.mark.smoke_pi

requires_pi = pytest.mark.skipif(not shutil.which("pi"), reason="pi 不在 PATH")
requires_pcl = pytest.mark.skipif(not PCL_BIN.exists(), reason="未找到 pcl 可执行")


class _Session:
    """RPC 驱动 /pcl 命令并收集 notify 事件。"""

    def __init__(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PCL_BIN", str(PCL_BIN))
        self.notifies: list[str] = []
        self.bridge = PiBridge(pi_bin="pi", connector_path=str(CONNECTOR),
                               timeout=300)
        # transport 在构造时绑定回调——必须在 start() 前替换实例属性
        orig = self.bridge._handle_frame

        def spy(obj):
            if obj.get("type") == "extension_ui_request" \
                    and obj.get("method") == "notify":
                self.notifies.append(str(obj.get("message") or ""))
            return orig(obj)

        self.bridge._handle_frame = spy
        self.bridge.start()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.bridge.close()

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
        pytest.skip("pcl-connector 不在预期位置")
    with _Session(tmp_path, monkeypatch) as s:
        resp = s.send_command(f"/pcl gen {DATA / 'demo.pcl'}")
        assert resp is not None and resp.get("success")
        assert any("完成" in n for n in s.notifies)


@requires_pi
@requires_pcl
def test_pcl_version_passthrough(tmp_path, monkeypatch):
    if not CONNECTOR.exists():  # pragma: no cover
        pytest.skip("pcl-connector 不在预期位置")
    with _Session(tmp_path, monkeypatch) as s:
        resp = s.send_command("/pcl version")
        assert resp is not None and resp.get("success")
        assert any("完成" in n for n in s.notifies)


@requires_pi
@requires_pcl
def test_pcl_run_forward_only_rejected(tmp_path, monkeypatch):
    if not CONNECTOR.exists():  # pragma: no cover
        pytest.skip("pcl-connector 不在预期位置")
    with _Session(tmp_path, monkeypatch) as s:
        resp = s.send_command(f"/pcl run {DATA / 'demo.pcl'} --agent null")
        assert resp is not None and resp.get("success")   # 命令本身完成
        assert any("被拒" in n for n in s.notifies)


@requires_pi
@requires_pcl
def test_pcl_run_save_without_model(tmp_path, monkeypatch):
    """:save 冒烟（M3 验收项）：无 pass → 不涉 LLM，token 经合成 get_state 取得。"""
    if not CONNECTOR.exists():  # pragma: no cover
        pytest.skip("pcl-connector 不在预期位置")
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
def test_pcl_run_new_ctx_a520(tmp_path, monkeypatch):
    """:new → 嵌入会话替换拒绝 → A520 → 退出码 3（M4 前的接续护栏）。"""
    if not CONNECTOR.exists():  # pragma: no cover
        pytest.skip("pcl-connector 不在预期位置")
    tpl = tmp_path / "new.pcl"
    tpl.write_text("A\n${:new}\nB\n", encoding="utf-8")
    out = tmp_path / "out.txt"
    with _Session(tmp_path, monkeypatch) as s:
        resp = s.send_command(f"/pcl run {tpl} -o {out}", timeout=120)
        assert resp is not None and resp.get("success")
        assert any("退出码 3" in n for n in s.notifies)


@requires_pi
@requires_pcl
def test_pcl_run_embedded_e2e(tmp_path, monkeypatch):
    """/pcl run 全链路：pass + pcl_write 写回 + 分支（真 LLM）。"""
    if not CONNECTOR.exists():  # pragma: no cover
        pytest.skip("pcl-connector 不在预期位置")
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
