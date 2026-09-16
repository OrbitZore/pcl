# PCL — 提示词控制语言

[English](README.md) | **简体中文**

编排 LLM/agent 的模板 DSL：**模板层是 PCL，脚本层是真 Python**。

[![CI](https://github.com/USER/pcl/actions/workflows/ci.yml/badge.svg)](https://github.com/USER/pcl/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pclang.svg)](https://pypi.org/project/pclang/)
[![Python](https://img.shields.io/pypi/pyversions/pclang.svg)](https://pypi.org/project/pclang/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## PCL 是什么？

PCL 将 `.pcl` 模板编译为可读的 Python 源码并在同一解释器中执行——完整复用 Python 生态（含 C 扩展），运行时零第三方依赖。

首个适配的 agent 是 [pi](https://github.com/earendil-works/pi-coding-agent)：正向模式拉起 `pi --mode rpc` 完成 pass 交互与上下文管理；嵌入模式在 pi 会话内经 `/pcl` 命令族直接执行。

```text
${SCORE = 0}

${:pass :write SCORE}
请就以下主题写一段话，并把自评质量分（0..10 整数）写入 SCORE：
$prompt

${:if SCORE >= 7}
质量达标，结束。
${:else}
分数不够，重写一遍，把新分数写入 SCORE。
${:fi}
```

## 安装

```bash
pip install pclang        # 或：pipx install pclang / uvx pclang
```

要求 Python ≥ 3.10，运行时零依赖。

安装 pi 连接器（正向 `--agent pi` 与嵌入 `/pcl` 命令族）：

```bash
pi install git:github.com/USER/pcl --directory pcl-connector/pi
# PyPI 发布后：pi install npm:pcl-connector-pi
```

## 快速上手

```bash
# 纯模板调试（无需 LLM）
pcl run examples/demo.pcl "为什么天空是蓝色的" --agent null

# 使用真实 agent
pcl run examples/demo.pcl "为什么天空是蓝色的" --agent pi

# 实时观察循环进度
pcl run examples/review-prove.pcl "高铁为什么不能用有砟轨道" --trace

# 查看生成的 Python 源码
pcl gen examples/demo.pcl
```

更多示例见 [examples/](examples/)。

## 文档

| 页面 | 说明 |
|------|------|
| [语言规范](docs/dsl.md) | 完整语法：构造、指令、pass 语义 |
| [实现设计](docs/design.md) | 架构、编译管线、运行时、桥接层 |
| [设置文件](docs/settings.md) | 用户级与项目级配置 |
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
git clone https://github.com/USER/pcl.git
cd pcl/pclang
uv venv && uv pip install -e ".[dev]"
python -m pytest                    # 单元 + e2e 测试
python -m pytest -m smoke_pi       # 集成测试（需 pi + 模型）
ruff check src tests                # 代码检查
```

## 贡献

参见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可

[MIT](LICENSE)
