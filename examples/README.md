# PCL 示例集

按场景组织的可运行用例。运行方式：`pcl run <文件.pcl> "<prompt>"`（默认
`--agent pi`，需已配置模型；连接器安装见主 [README](../README.md)）。
纯模板调试可加 `--agent null`（reply=prompt 原文，无 LLM）。

| 用例 | 场景 | 机制要点 |
|---|---|---|
| [demo.pcl](demo.pcl) | 单轮自评：写作 + 评分 + 分支 | `$prompt` 裸糖、`:pass :write`、`:if/:else` |
| [review-prove.pcl](review-prove.pcl) | **审查报告 → 自证循环，直到全部主张可信** | `:while` + `:break`、结构化写回（字符串数组）、跨轮状态（PENDING）、`:function` 内 pass |
| [plan-review.pcl](plan-review.pcl) | **方案制作 → 自评循环，10 分制直到 10 分** | `:while` 阈值循环、整数写回校验（bool 陷阱防护）、轮次上限 |
| [data-analysis.pcl](data-analysis.pcl) | 结构化数据按需拉取 | Python 侧造数、`:read` 快照、agent 经 `pcl_read` 取数（不拼进 prompt） |
| [context-session.pcl](context-session.pcl) | 上下文接续 | `:save`/`:new`/`:load` 往返、会话记忆验证 |
| [use-library.pcl](use-library.pcl) + [greetlib.pcl](greetlib.pcl) | 库复用 | `.pcl` 间 `import`、加载层（import 永不触发 agent）、模板函数跨文件调用 |

## 快速开始

```bash
# ① 无 agent 依赖（纯模板渲染）
pcl run use-library.pcl --agent null

# ② 单轮（约 1 次 LLM 调用）
pcl run demo.pcl "为什么天空是蓝色的"

# ③ 循环场景（多轮，每轮 1 次 LLM 调用；上限内置）
pcl run review-prove.pcl "夜间高铁为什么要减速"
pcl run plan-review.pcl "为 10 人团队制定一次季度技术分享会方案"

# ④ 数据/上下文
pcl run data-analysis.pcl
pcl run context-session.pcl

# 查看任一示例生成的 Python 源
pcl gen review-prove.pcl
```

## 提示

- 循环用例的每轮 agent 回复都会按宏语义落入输出文档（可 `--trace` 观察流式）；
- 跨运行续聊：把 `:save` 得到的 token 存进文件，下次 `${cx = open(...).read().strip()}` + `${:load cx}`（DSL §8 配方）；
- 全部示例经 `tests/test_examples.py` 编译守护（`pcl check` 等价）。
