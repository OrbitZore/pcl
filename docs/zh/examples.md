# 示例导览

全部在 [`examples/`](https://github.com/OrbitZore/pcl/tree/main/examples)
目录，可直接运行（shebang + `chmod +x`）。

运行方式：`pcl run <file.pcl> "<prompt>"`（默认 `--agent pi`，需已
配置模型；连接器安装见 [快速开始](quickstart.md)）。纯模板调试加
`--agent null`。

## goal-loop — 目标达成循环

```bash
./goal-loop.pcl "Create a file named hello.txt with content Hello PCL"
```

/goal 式：每 pass（执行/检查）开新上下文（`:new`），prompt 自包含
（目标 + 累积历史 + 轮次）；`:if` 条件在写回后求值——达成即 `:break`。

## review-prove — 审查自证循环

```bash
./review-prove.pcl "Remote work is better than office work" --trace
```

多轮审查观点直到全部可信。展示：`:while` + `:break`、结构化写回
（dict）、跨轮状态、`:new` 隔离、`$(# … #)` 注记终态。

## plan-review — 方案自评循环

```bash
./plan-review.pcl "Plan a quarterly tech sharing session"
```

方案制作 → 打分循环直到 10/10（或轮次上限）。展示：阈值循环、
整数写回校验。

## data-analysis — 结构化数据拉取

```bash
./data-analysis.pcl
```

Python 侧造数，agent 经 `pcl_read` 按需取数（不拼进 prompt）。
展示：`:read` 快照。

## context-session — 上下文接续

```bash
./context-session.pcl
```

`:save` → `:new` → `:load` 往返，验证会话记忆。

## use-library — 模板库复用

```bash
./use-library.pcl --agent null
```

`.pcl` 间 `import`、模板函数跨文件调用。展示：加载层
（import 永不触发 agent）。

## hello — shebang 直执行

```bash
./hello.pcl "Quantum entanglement"
```

`#!/usr/bin/env pcl` + `chmod +x` 的最小示例。
