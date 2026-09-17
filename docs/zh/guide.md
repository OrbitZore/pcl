# 核心指南

面向使用者的概念与模式。规范性定义见 [RFC 0000](https://github.com/OrbitZore/pcl/blob/main/rfc/rfc-0000-language.zh.md)。

## 双层模型

- **模板层**：文本 + `${…}` 构造。你写的是"带控制流的提示词模板"
- **脚本层**：`${…}` 和 `$(…)` 里是真 Python——表达式、赋值、import、
  标准库、第三方库，全部原生

产物 = 输出文档（stdout 或 `-o` 文件）+ 副作用（agent 交互、上下文切换）。

## 插值双形式

| 写法 | 冲刷 | 用途 |
|---|---|---|
| `${表达式}` | 构造即冲刷点，独立 emit，**行号 1:1** | 主力；副作用保序 |
| `$(表达式)` | 从不冲刷，织入合并段 | 同一行内拼接多个值 |

经验法则：**默认用 `${}`**；一行内拼多个值或想精确控制空行时用 `$()`。
纯语句（赋值/import）两种都静默执行；副作用调用加 `_ =` 前缀。

```text
${import json}
${items = ["a", "b"]}
共 ${len(items)} 项：$(json.dumps(items))          ← 同一行：${} + $() 混用
```

## pass：与 agent 的一次交互

```text
${:pass :read MY_VAR :write RESULT}
<prompt 文本——可以是文本与插值的任意组合>
```

生命周期：

1. **渲染**：prompt 体渲染到独立缓冲（不进输出文档）
2. **提交**：遇到下一个指令或文件结尾自动提交（内部去首尾空白）
3. **等待**：agent 完成本轮；期间可用 `pcl_read` 读快照、`pcl_write` 写回
4. **写回**：`:write` 声明的变量被赋值；reply 同时写入输出文档和变量 `reply`

要点：

- `:read X`——pass 开始时冻结 X 的快照给 agent 看（防渲染后变动）
- `:write X`——**唯一授权名**。agent 平铺写 dict（如
  `{"done": true}` 而非 `{"X": {...}}`）会自动包装；混写授权名+其他名 → R406
- 空 prompt 直接跳过（不调 agent）
- pass 体内的 `${}` 会先执行再提交——**想在写回后处理结果，把语句放到
  pass 之后的指令边界外**（见下）

### 写回后处理：指令边界

pass 体结束于**下一个指令**。写回值只在提交后存在，所以后处理语句
必须放在指令之后：

```text
${:pass :write W}
执行者：…… 写入 {"W": "行动摘要"}

${HISTORY = HISTORY + (W if isinstance(W, str) else str(W)) + "\n"}   ← 在 :new 之后，pass 体外
${:new}
${:pass :write W}
检查者：已有行动：$(HISTORY)…… 写入 {"W": {"done": true/false}}
${:if isinstance(W, dict) and W.get("done")}    ← :if 条件在写回之后求值
    ${:break}
${:fi}
```

两种读写回值的正确位置：**下一个指令之后**（如 `${:new}` 后的纯语句），
或 **`:if` 等指令的条件表达式**（在写回后求值）。

## 上下文管理：:new / :save / :load

| 指令 | 作用 |
|---|---|
| `${:new}` | 开新会话——**清空全部历史**（agent 看不到之前发生了什么） |
| `${:save 名}` | 保存当前会话，`名` = opaque token |
| `${:load 名}` | 切回保存的会话 |

- `:new` 后的 pass **prompt 必须自包含**（目标、历史、轮次都要写进去）
- token 跨运行持久化自己管：`${open("ctx.txt","w").write(TOKEN)}`

## 模式：goal 达成循环

每轮执行+检查、达成即停（完整可运行版见 [examples/goal-loop.pcl](https://github.com/OrbitZore/pcl/blob/main/examples/goal-loop.pcl)）：

```text
${:while ROUND < MAX}
    ${ROUND = ROUND + 1}
    ${:new}
    ${:pass :write W}        ← Pass 1：执行（prompt 自包含）
    ${HISTORY = HISTORY + W + "\n"}   ← 指令后：读 Pass 1 写回值
    ${:new}
    ${:pass :write W}        ← Pass 2：检查
    ${:if isinstance(W, dict) and W.get("done")}
        ${DONE = True}
        ${:break}
    ${:fi}
${:done}
```

## 注记与上下文注入

| 构造 | 去向 | 典型用途 |
|---|---|---|
| `$(# … #)` 注记 | 独立运行 → 输出文档；嵌入运行 → 会话内条目（**不进 LLM 上下文**） | 轮次进度、终态结论 |
| `$(@ … @)` 上下文注入 | 作为独立用户消息进 agent 会话（**不触发推理**） | 任务目标声明、背景资料 |

两者都是完整模板体——内部可以再用 `${}`/`$()`/指令。内容里出现定界符
字面时用扩展形式：`$(end# … #end)`、`$(tag@ … @tag)`。

## 指令速查

| 指令 | 作用 |
|---|---|
| `${:if}/${:elif}/${:else}/${:fi}` | 条件 |
| `${:while …}${:done}` / `${:for X in …}${:done}` | 循环 |
| `${:break}` / `${:continue}` | 跳出/继续 |
| `${:function f(x)}…${:endfunction}` / `${:return}` | 函数 |
| `${:pass [:read X] [:write Y]}` | agent 交互 |
| `${:save T}` / `${:load T}` / `${:new}` | 上下文 |
| `${:# 注释}` / `${# 注释}` | 注释（须独占一行） |

## 与 pi 的两种集成

- **正向**：`pcl run --agent pi file.pcl`——PCL 拉起 headless 的
  `pi --mode rpc`，独立会话
- **嵌入**：pi 会话内 `/pcl run file.pcl`——pass 直接进**你当前的会话**；
  脚本里的 `:new`/`:load` 会切换你眼前的会话（有接管规则保护）
- `~/.pcl/bin/` 下的可执行 pcl 脚本自动注册为 `/pcl-<名字>` 命令
  （同样嵌入当前会话）
