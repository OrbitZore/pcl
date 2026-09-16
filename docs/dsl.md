# PCL 语言规范（Prompt Control Language）

- 版本：v0.2（实现态——依据 v0.1 终审冻结版 + 实现期演进）
- 实现：纯 Python 包 `pclang`（≥3.10，零第三方依赖），`.pcl` 编译为可读 Python 源并在同一解释器执行
- 首个 agent 适配：[pi](https://github.com/earendil-works/pi-coding-agent)（正向 `pcl run` + 嵌入 `/pcl run`）

---

## 1. 定位

**双层语言**：模板层是 PCL（文本 + `${…}` 构造），脚本层是真 Python（表达式/语句/库全为宿主解释器原生）。

程序产物 = 输出文档（stdout / `-o` 文件）+ 副作用（agent 交互、上下文切换、Python 副作用）。

**非目标**：自研函数库/类型系统；并行/多 agent；多行构造（三引号字符串除外）。

---

## 2. 词法结构

### 2.1 源文件

UTF-8（BOM 剥除；解码失败 → L102）；`.pcl` 后缀；首行 `#!` 忽略（shebang 直执行：`#!/usr/bin/env pcl` + `chmod +x`）。

### 2.2 构造与文本

| 构造 | 语法 | 语义 |
|---|---|---|
| **发起型插值** | `${STMTS}` | 构造即冲刷点：纯语句先冲刷再执行（保序）；表达式语句独立 `emit(text(EXPR))`，行号 1:1 |
| **合并型插值** | `$(STMTS)` | 从不冲刷：表达式立即求值暂存 `__pcl_tN`，织入合并段单条 emit |
| **指令** | `${:动词 …}` | 控制流/上下文/pass（§6） |
| **注释** | `${:# …}` 或 `${# …}` | 行界定（至行尾丢弃）；须独占一行（C305） |
| **注记** | `$(# … #)` | 完整模板体（递归 tokenize），渲染后经 `note()` 下发——不进 LLM 上下文 |
| **上下文注入** | `$(@ … @)` | 完整模板体，渲染后作为独立用户消息注入 agent 会话——不触发 LLM 推理 |
| **裸糖** | `$prompt` | 文本位置 ≡ `$(prompt)`（`$` + 完整标识符恰为 `prompt`） |
| **转义** | `$$` | → 字面 `$`（单遍成对消解） |

**扩展定界符**（同 C++ raw string，防止内容中出现 `#)` / `@)`）：

```text
$(end# 注记含 #) 字符 #end)       ← note，delim="end"
$(tag@ 上下文含 @) 字符 @tag)     ← context，delim="tag"
```

- 开头 `<delim>#`，结尾 `#<delim>)`——严格对称（marker 必须同为 `#` 或 `@`）
- `<delim>` 为 `\w+`（字母/数字/下划线）
- 闭合 `#<delim>)` 或 `@<delim>)` 须在后续源码中存在，否则回落为 Python 表达式

### 2.3 闭合规则

`${…}` 按 `}`、`$(…)` 按 `)`（tokenize 增量扫描：字符串/注释感知、括号配平）。三引号字符串内的换行允许构造跨行；指令一律单行。

### 2.4 空白与独行消除

- 行首/行尾 ASCII 空白剥除（空格/制表符）；`\r` 随行终止符剥离
- 独行消除：行内全部构造无输出 → 整行（含换行符）移除（指令、纯语句插值、注释、上下文注入）
- 空行保留（输出 `\n`）

---

## 3. 执行模型

1. **编译**：`.pcl` → 生成 Python 源（含 `# pcl:N` 行号标注）
2. **执行**：单模块两相——加载层（`:function` + 顶层 import/字面量赋值）+ `main(__pcl_prompt="")`
3. **输出**：文本/插值/pass 回复/注记经 `emit` 写入当前 sink
4. **交互**：`submit()` 阻塞至 agent 空闲，返回 `reply` 与 `writes`
5. **错误**：L/P/C（编译期 exit 1）、R（运行期 exit 2）、A（桥接 exit 3）、130（SIGINT）

---

## 4. 插值双形式

| | `${}` 发起型 | `$()` 合并型 |
|---|---|---|
| 冲刷 | 构造即冲刷点 | 从不冲刷 |
| 表达式 | 独立 `emit(text(EXPR))` 行号 1:1 | 立即求值暂存 `__pcl_tN`，织入合并段 |
| 纯语句 | 冲刷后原样执行 | 立即执行不打断合并段 |
| 保序 | ✅（副作用发射与前后文本保序） | 唯一不保证：求值期间发射副作用先于同段前置文本落 sink |
| 内容 | 任意 Python 简单语句列表（`;` 分隔；复合语句 → C300） | 同左 |

表达式语句的值**无条件**经 `text()` 插入（`None` → `null`）；赋值/import 等静默执行。副作用调用要 `_ =` 前缀丢弃返回值。

---

## 5. 注记与上下文注入

### 5.1 注记 `$(# … #)`

- 内容为**完整模板体**（递归 tokenize：支持 `${}`/`$()`/指令/裸糖/嵌套）
- 渲染结果经 `note()` 下发：
  - **独立运行**（`pcl run`）：渲染进输出文档（发起型保序）
  - **嵌入运行**（pi 内 `/pcl run`）：经连接器 `appendEntry("pcl-note")` 附加进会话流（`▌ <text>`，不进 LLM 上下文）
- 独行消除：注记行不消除（产生输出）

### 5.2 上下文注入 `$(@ … @)`

- 内容为完整模板体（同注记）
- 渲染结果作为**独立用户消息**注入 agent 会话上下文：
  - **forward**：经 RPC `steer` 命令排队（idle 时不触发推理，下一 prompt 时投递）
  - **embed**：经 `context` 命令 → 连接器 `sendMessage(triggerTurn=false)` — 进入上下文，不触发
- **不触发 LLM 推理**——下一个 `${}` 构造或模板结尾不因此触发
- 独行消除：上下文注入行消除（不产生主输出）

---

## 6. 指令参考

| 指令 | 位置 | 生成 Python |
|---|---|---|
| `${:if EXPR}` / `${:elif}` / `${:else}` / `${:fi}` | 任意 | `if`/`elif`/`else` 块 |
| `${:while EXPR}` … `${:done}` | 任意 | `while` 块 |
| `${:for X in EXPR}` … `${:done}` | 任意 | `for` 块 |
| `${:break}` / `${:continue}` | 循环内 | `break` / `continue` |
| `${:function NAME(params)}` … `${:endfunction}` | 顶层 | `def NAME(params):` |
| `${:return [EXPR]}` | 函数内 | `return (EXPR)` |
| `${:pass [:read 名] [:write 名]}` | 任意 | §7 |
| `${:save 名}` / `${:load 名}` / `${:new}` | 任意 | `名 = save()` / `load(名)` / `new_ctx()` |
| `${:#}` / `${#}` 注释 | 独行 | 丢弃 |

---

## 7. pass 语义

```
${:pass :read CTX :write SCORE}
<prompt 体：文本、插值——直至下一个指令构造>
${:return EXPR}     ← 指令先提交后执行
```

- prompt 独立 sink（隔离于输出文档）；遇下一个指令或 EOF 自动提交（内部 trim）
- `:read` 单变量快照（pass 开始预序列化冻结，agent 经 `pcl_read` 按名拉取）
- `:write` 单变量写回（agent 经 `pcl_write` 写入；**自动包装**：唯一授权名 + agent 平铺写 dict → 自动嵌套）
- reply 经 `emit` 追加到当前 sink + 存入变量 `reply`
- 空 prompt 跳过（不调桥接）；空回复 → A504；越权写 → R406（先于 A504）
- `:write` 深度上限 32（JSON 反序列化）

---

## 8. 上下文

- `:save 名` → token = pi sessionFile（opaque str）
- `:load 名` → 切换到 token 会话（本地文件存在性预检 → R430）
- `:new` → 新建匿名上下文
- 跨运行持久化：token 存取到自己的文件（普通 Python 读写）
- 嵌入形态接续（`:new`/`:load` 涉及会话替换）：模块级桥/接管规则/auto-follow/A520–A523

---

## 9. 模块与 import

- `.pcl` ≡ Python 模块：加载层 = `:function` + 顶层 import/字面量赋值；`main(prompt)` = 模板体
- `import pcl; pcl.install_importer()` 后 `import mytpl`；DSL 内 `${import helpers}`
- `.py` 优先；import 永不触发 agent

---

## 10. text() 规则

| 类型 | 输出 |
|---|---|
| `str` | 原样 |
| `None` | `null` |
| `bool` | `true`/`false` |
| `int` | 十进制 |
| `float` | round-trip repr |
| `dict/list/tuple` | 紧凑 JSON（`ensure_ascii=False`；tuple 视作 list；键碰撞退化 `str(v)`） |
| 其他 | `str(v)` |

---

## 11. 运行时保留名（10 个）

`emit` `text` `submit` `save` `load` `new_ctx` `push_sink` `pop_sink` `note` `context`

任何绑定目标与之同名 → C300。`:function` 名 `main`/`prompt`/`reply` 保留 → C300。`__pcl_` 前缀保留。

---

## 12. 错误与退出码

| 类 | 码 | 退出码 |
|---|---|---|
| L | L100–L102 | 1 |
| P | P200–P203 | 1 |
| C | C300/C305/C310 | 1 |
| R | R400/R405/R406/R409/R430/R431 | 2 |
| A | A500–A523 | 3 |
| SIGINT | R409 | 130 |

---

## 13. 完整示例

```text
${import json}
${ROUND = 0}
${BRAINSTORM = []}
${TOPIC = prompt}

${:pass :write BRAINSTORM}
请对 $(TOPIC) 发散列出所有正反向观点，写入 BRAINSTORM。

${:while ROUND < 4}
    ${ROUND = ROUND + 1}
    ${:new}
    ${:pass :write RESULT}
    请审查以下观点：$(json.dumps(BRAINSTORM))
    结果写入 RESULT：{"all": [...], "pending": [...]}
    ${ALL = RESULT.get("all") or BRAINSTORM}
    ${PENDING = RESULT.get("pending") or []}
    ${:if len(PENDING) == 0}${:break}${:fi}
${:done}

$(#
✔ 第 $(ROUND) 轮全部可信，共 $(len(ALL)) 条：
${:for c in ALL}
- $(c)
${:done}
#)
```
