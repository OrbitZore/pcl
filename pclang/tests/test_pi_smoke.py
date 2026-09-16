"""smoke-pi：真 pi 的集成冒烟（DESIGN §11；需 pi 二进制，pass 类另需已配置模型）。

- `test_connector_probe`：连接器加载（jiti）+ /pcl 注册 + 上下文三指令映射
  （不需要模型）；
- `test_pass_no_model_a501`：无模型时 pass 走 A501 错误路径——验证信令分发、
  payload 解析与 extension_error 流出的完整链路；
- `test_pass_write_e2e`：完整 pass + pcl_write 写回（真 LLM 轮次）；
- `test_context_roundtrip_e2e`：同会话续聊 + :save/:new/:load 上下文往返。

M2 冒烟实测记录（2026-09，pi@0.85.1，DESIGN §8.2 预期修正）：
① ``pi.sendUserMessage`` 为发后即忘（源码 ``.catch(...)`` 不返回 promise），
  prompt 的 response ok 在预检通过时即发出、**早于** ``agent_settled``——
  settled 是唯一 pass 边界，response 仅作屏障；
② 工具参数顶层开放形状（``Type.Record`` 直接作 parameters /
  ``additionalProperties``）会被参数校验层剥空，命名键承载完好——
  pcl_write 经 ``values`` 键嵌套，桥侧解包。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from pcl.errors import PclError
from pcl.pibridge import PiBridge

CONNECTOR = (Path(__file__).resolve().parent.parent.parent
             / "pcl-connector" / "pi" / "extensions" / "index.ts")

pytestmark = pytest.mark.smoke_pi

requires_pi = pytest.mark.skipif(not shutil.which("pi"), reason="pi 不在 PATH")


def _needs_connector():
    if not CONNECTOR.exists():  # pragma: no cover
        pytest.skip("pcl-connector/pi/extensions/index.ts 不在预期位置")


def _model_configured(b: PiBridge) -> bool:
    resp = b._call({"type": "get_state"})
    return bool((resp.get("data") or {}).get("model"))


@requires_pi
def test_connector_probe():
    """连接器经 -e 加载：/pcl 注册唯一、命名/重取映射正确（不需要模型）。"""
    _needs_connector()
    b = PiBridge(pi_bin="pi", connector_path=str(CONNECTOR), timeout=60)
    b.start()
    try:
        token = b.save()   # 命名 + 重取（§8.3）
        assert token.endswith(".jsonl")
        assert ".pi/agent/sessions/" in token.replace("\\", "/")
        # R20 惰性落盘：无 assistant 回复时文件可能尚未写盘——此时 :load 预检 R430
        if not Path(token).is_file():
            with pytest.raises(PclError, match="R430"):
                b.load(token)
    finally:
        b.close()


@requires_pi
def test_pass_no_model_a501():
    """无模型：信令分发/payload 解析全链路可达，终以 A501 失败化。"""
    _needs_connector()
    b = PiBridge(pi_bin="pi", connector_path=str(CONNECTOR), timeout=60)
    b.start()
    try:
        if _model_configured(b):
            pytest.skip("模型已配置，改跑 e2e 用例")
        with pytest.raises(PclError) as ei:
            b.submit("你好", {}, ())
        assert ei.value.code in ("A501", "A502")
    finally:
        b.close()


@requires_pi
def test_pass_write_e2e():
    """完整 pass：回复 + pcl_write 写回（真 LLM 轮次）。"""
    _needs_connector()
    b = PiBridge(pi_bin="pi", connector_path=str(CONNECTOR), timeout=300)
    b.start()
    try:
        if not _model_configured(b):
            pytest.skip("未配置模型")
        r = b.submit(
            "调用 pcl_write 把整数 7 写入 SCORE，然后只回复一个字：好。",
            {}, ("SCORE",))
        assert r.reply.strip()
        assert r.writes.get("SCORE") == 7
    finally:
        b.close()


@requires_pi
def test_context_roundtrip_e2e():
    """同会话续聊（上下文连续）+ :save/:new/:load 往返。"""
    _needs_connector()
    b = PiBridge(pi_bin="pi", connector_path=str(CONNECTOR), timeout=300)
    b.start()
    try:
        if not _model_configured(b):
            pytest.skip("未配置模型")
        r = b.submit(
            "调用 pcl_write 把整数 7 写入 SCORE，然后只回复一个字：好。",
            {}, ("SCORE",))
        assert r.writes.get("SCORE") == 7
        # 同会话续聊：看得到上一轮
        r2 = b.submit("上一轮 pcl_write 写入 SCORE 的值是多少？只回复数字。", {}, ())
        assert "7" in r2.reply
        # 上下文往返
        token = b.save()
        if Path(token).is_file():
            b.new_ctx()
            b.load(token)
            r3 = b.submit("SCORE 曾被写入的值是多少？只回复数字。", {}, ())
            assert "7" in r3.reply
    finally:
        b.close()
