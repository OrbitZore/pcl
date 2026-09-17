# PCL — 提示词控制语言

[English](README.md) | **简体中文**

编排 LLM/agent 的模板 DSL：**模板层是 PCL，脚本层是真 Python**。

[![Docs](https://img.shields.io/badge/docs-orbitzore.github.io%2Fpcl-blue)](https://orbitzore.github.io/pcl/)
[![CI](https://github.com/OrbitZore/pcl/actions/workflows/ci.yml/badge.svg)](https://github.com/OrbitZore/pcl/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pclang.svg)](https://pypi.org/project/pclang/)
[![Python](https://img.shields.io/pypi/pyversions/pclang.svg)](https://pypi.org/project/pclang/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

---

## PCL 是什么？

PCL 将 `.pcl` 模板编译为可读的 Python 源码并在同一解释器中执行——完整复用 Python 生态（含 C 扩展），运行时零第三方依赖。

首个适配的 agent 是 [pi](https://github.com/earendil-works/pi-coding-agent)：正向模式拉起 `pi --mode rpc` 完成 pass 交互与上下文管理；嵌入模式在 pi 会话内经 `/pcl` 命令族直接执行。

/goal 式目标达成循环（同其他 agent 的 /goal 功能：每个 pass 经 :new 开新上下文，因此 prompt 必须自包含——目标 + 累积行动历史 + 轮次）：

```text
${ROUND = 0}
${DONE = False}
${W = ""}
${HISTORY = ""}
${MAX = 100}

${:while ROUND < MAX}
    ${ROUND = ROUND + 1}

    ${:new}
    ${:pass :write W}
    执行者（第 $(ROUND)/$(MAX) 轮）。新上下文——所需信息如下。
    任务目标：$(prompt)
    已有行动：
    $(HISTORY if HISTORY else "（无——第 1 轮）")
    采取下一步行动，然后只调用一次 pcl_write 写入：
    {"W": "行动摘要"}

    ${:new}
    ${HISTORY = HISTORY + (W if isinstance(W, str) else str(W)) + "\n"}
    ${:pass :write W}
    检查者（第 $(ROUND)/$(MAX) 轮）。新上下文——依以下证据判断。
    任务目标：$(prompt)
    已有行动：
    $(HISTORY)
    只调用一次 pcl_write 写入：
    {"W": {"done": true/false, "note": "理由"}}

    ${:# :if 条件在写回之后求值——W 即 Pass 2 的结果}
    ${:if isinstance(W, dict) and W.get("done")}
        ${DONE = True}
        ${:break}
    ${:fi}
    $(# 第 $(ROUND) 轮 — ⏳ 进行中 #)
${:done}

${:if DONE}
$(# 🎉 目标在第 $(ROUND)/$(MAX) 轮达成#)
${:fi}
```

## 稳定性

1.0 之前，从 alpha 起步（`0.2.0a1`，见
[版本号计划](CONTRIBUTING.zh-CN.md#versioning-plan版本号计划)）：

- **本 README 展示的语法子集 = 稳定面**——alpha 期间不发生破坏性变更
- 超出部分（完整定义：[RFC 0000](rfc/rfc-0000-language.zh.md)）可能演进
- 连接器协议经 `pcl version` 握手对齐版本

## 安装

```bash
pip install pclang        # 或：pipx install pclang / uvx pclang
```

要求 Python ≥ 3.10，运行时零依赖。

安装 pi 连接器（正向 `--agent pi` 与嵌入 `/pcl` 命令族）：

```bash
pi install npm:pcl-connector-pi
# 可选开发源：pi install git:github.com/OrbitZore/pcl
```

## 快速上手

```bash
# 纯模板调试（无需 LLM）
pcl run examples/hello.pcl "为什么天空是蓝色的" --agent null

# 真实 agent（目标循环：每轮执行+检查，达成即停）
pcl run examples/goal-loop.pcl "在当前目录创建 hello.txt，内容为 Hello PCL" --agent pi

# 实时观察循环进度
pcl run examples/review-prove.pcl "高铁为什么不能用有砟轨道" --trace

# 查看生成的 Python 源码
pcl gen examples/hello.pcl
```

更多示例见 [examples/](examples/)。

### 在 pi 会话内使用（嵌入形态）

装好连接器后，模板可以直接在你的 pi 对话里运行——pass 进入
**你当前的会话**：

```text
/pcl run ./examples/goal-loop.pcl "在当前目录创建 hello.txt，内容为 Hello PCL"
```

把可执行 `.pcl` 脚本放进 `~/.pcl/bin/`——自动注册为 pi 斜杠命令
（路径展平、一律嵌入运行）：

```bash
mkdir -p ~/.pcl/bin && cp examples/goal-loop.pcl ~/.pcl/bin/
chmod +x ~/.pcl/bin/goal-loop.pcl
# 重启 pi 后：
/pcl-goal-loop "在当前目录创建 hello.txt，内容为 Hello PCL"
```

## 文档

| 页面 | 说明 |
|------|------|
| **[文档站](https://orbitzore.github.io/pcl/)** | 双语用户文档（中文 / English） |
| [快速开始与指南](docs/zh/index.md) | 用户文档（中文 / English） |
| [语言参考](docs/zh/language.md) | 速查：构造、指令、pass 语义 |
| [RFC 规范](rfc/README.md) | 语言定义 / 执行层 / 连接器（开发者向） |
| [设置](docs/zh/settings.md) | 用户级与项目级配置 |
| [示例集](examples/) | 可运行场景：循环、上下文、数据分析、库复用 |

## 核心概念

| 概念 | 语法 | 作用 |
|------|------|------|
| 插值 | `${expr}` / `$(expr)` | 发射表达式值（发起型/合并型） |
| 控制流 | `${:if}` `${:for}` `${:while}` | 等价 Python 块 |
| Agent 交互 | `${:pass :write VAR}` | 一轮 LLM 交互 + 结构化写回 |
| 上下文 | `${:save ctx}` `${:load ctx}` `${:new}` | 会话管理（保存/切换/新建） |
| 注记 | `$(# text #)` | 渲染注解——不进 LLM 上下文 |
| 上下文注入 | `$(@ text @)` | 注入为用户消息但不触发推理 |
| 原始文本 | `${r"""…"""}` | 多行字面量，不插值 |

## 开发

```bash
git clone https://github.com/OrbitZore/pcl.git
cd pcl/pclang
uv venv && uv pip install -e ".[dev]"
python -m pytest                    # 单元 + e2e 测试
python -m pytest -m smoke_pi       # 集成测试（需 pi + 模型）
ruff check src tests                # 代码检查
```

## 贡献

参见 [CONTRIBUTING.zh-CN.md](CONTRIBUTING.zh-CN.md)（English: [CONTRIBUTING.md](CONTRIBUTING.md)）。

## 许可

[GPL-3.0](LICENSE)
