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
#    回复只在每轮结束时落 stdout——长循环建议开 --trace 看 stderr 实时进度：
#    pass 提交 / 思考与文本增量（暗色）/ pcl_write 写回 / 轮次结束
pcl run review-prove.pcl "高铁为什么不能用有砟轨道" --trace
pcl run plan-review.pcl "为 10 人团队制定一次季度技术分享会方案" --trace

# ④ 数据/上下文
pcl run data-analysis.pcl
pcl run context-session.pcl

# 查看任一示例生成的 Python 源
pcl gen review-prove.pcl
```

## 提示

- **stdout = 输出文档**（文本/插值/每轮回复，轮末才落）；**stderr = 诊断**（错误、
  `--trace` 实时进度）；退出码 0/1/2/3/130（成功/用法与编译/运行期/桥接/中断）；
- 跨运行续聊：把 `:save` 得到的 token 存进文件，下次 `${cx = open(...).read().strip()}` + `${:load cx}`（DSL §8 配方）；
- 全部示例经 `tests/test_examples.py` 编译守护（`pcl check` 等价）。
