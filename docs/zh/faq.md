# FAQ

## 模板执行到一半报 R406（越权写入）？

agent 写了 `:write` 没声明的名字。两种可能：

1. agent 平铺写 dict（`{"done": true}`）——若全部键越权会**自动包装**，
   不报错；报错说明是**混写**（授权名 + 其他名都有）
2. 提示词里明确写："只调用一次 pcl_write，写入 {"W": {...}}"
   （嵌套到授权名下），并加一句"之后不要再调用"

## pass 里写的 `${X = W.get(...)}` 拿到的是旧值？

pass 体在**提交之前**渲染——此时写回还没发生。把后处理语句放到
pass 之后的指令边界外（如 `${:new}`/`${:if}` 之后），或直接用
`:if` 条件表达式（在写回后求值）。见 [核心指南 · 写回后处理](guide.md#写回后处理指令边界)。

## C305 注释必须独占一行？

`${:# …}` 是行界定注释，独占一行（允许缩进）。要在行内标注用
纯 Python：`${_ = None  # 说明}`。

## 没有 agent / 没配模型怎么调试？

```bash
pcl run --agent null file.pcl "测试"   # reply = prompt 原样，不调 LLM
```

模板逻辑（插值、循环、分支）全部照常执行。

## 想看生成了什么 Python？

```bash
pcl gen file.pcl
```

输出带 `# pcl:N` 行号标注的可读源码；报错时 traceback 也回指模板行。

## `:new` 之后 agent 好像"失忆"了？

`:new` 开新会话，**清空全部历史**（包括 `$(@ @)` 注入的上下文）。
这是特性不是 bug——新上下文里的 pass prompt 必须自包含（目标、
历史、轮次都要写进去）。想保留历史就去掉 `:new`。

## `$(prompt)` 是什么？

模板收到的第一个位置参数。`pcl run x.pcl "任务"` → `prompt = "任务"`。
裸糖 `$(prompt)` ≡ `$(prompt)`；缺省 `""`。

## 输出里 dict 变成了 JSON？

`text()` 规则：dict/list/tuple → 紧凑 JSON（`ensure_ascii=False`），
`None` → `null`，`bool` → `true/false`。要自定义格式自己
`json.dumps(..., indent=2)`。

## 嵌入运行（/pcl run）里 `:new` 会怎样？

会**切换你当前的 pi 会话**（旧会话自动落盘）。有接管规则保护：
auto-follow、绑定降级 A523、跨 cwd 拒绝。详见
[RFC 0002 §7](https://github.com/OrbitZore/pcl/blob/main/rfc/rfc-0002-connector.zh.md)。

## 退出码 1/2/3 分别是什么？

1 = 编译期（L/P/C），2 = 运行期（R），3 = 桥接（A），130 = 中断。
完整错误码表见 [语言参考](language.md#错误码速查)。

## 如何贡献新特性？

先写 RFC——见
[CONTRIBUTING](https://github.com/OrbitZore/pcl/blob/main/CONTRIBUTING.zh-CN.md)。
