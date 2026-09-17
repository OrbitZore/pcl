---
Number: 0000
Title: PCL Language Definition
Status: Implemented
Type: Standards Track
Created: 2026-09-17
Language: 中文（权威稿；英文镜像见同名 .md）
Implementation: pclang ≥ 0.2.0
---

# RFC 0000 — PCL Language Definition（语言定义）

## Summary

PCL（Prompt Control Language）是编排 LLM agent 的模板 DSL。**双层语言**：
模板层是 PCL（文本 + `${…}` 构造），脚本层是真 Python（表达式、语句、
标准库与第三方库均为宿主解释器原生）。程序产物 = 输出文档
（stdout / `-o` 文件）+ 副作用（agent 交互、上下文切换、Python 副作用）。

**非目标**：自研函数库/类型系统；并行/多 agent 编排；多行构造
（三引号字符串内的换行除外）。

## Motivation

现有 agent 编排要么把逻辑锁死在私有 DSL 里（无生态、难调试），要么
退化为纯代码框架（模板与代码混杂、prompt 难维护）。PCL 取两者之长：
**提示词模板可读、控制流声明式，但一切计算都是宿主 Python**——
零学习成本、零生态损失、traceback 直指模板行。

## Specification

### 1. 源文件

- UTF-8（BOM 剥除；解码失败 → L102）；惯例后缀 `.pcl`
- 首行 `#!` 忽略（shebang 直执行：`#!/usr/bin/env pcl` + `chmod +x`）

### 2. 构造（constructs）

| 构造 | 语法 | 语义 |
|---|---|---|
| **发起型插值** | `${STMTS}` | 构造即冲刷点：纯语句先冲刷再执行（保序）；表达式语句独立 `emit(text(EXPR))`，行号 1:1 |
| **合并型插值** | `$(STMTS)` | 从不冲刷：表达式立即求值暂存，织入合并段单条 emit |
| **指令** | `${:动词 …}` | 控制流 / 上下文 / pass（§6） |
| **注释** | `${:# …}` / `${# …}` | 行界定（至行尾丢弃）；须独占一行（C305） |
| **注记** | `$(# … #)` | 完整模板体（递归 tokenize）；渲染后经 `note()` 下发——不进 LLM 上下文 |
| **上下文注入** | `$(@ … @)` | 完整模板体；渲染后作为独立用户消息注入 agent 会话——不触发 LLM 推理 |
| **转义** | `$$` | → 字面 `$`（单遍成对消解） |

**扩展定界符**（防内容中出现定界符字面；同 C++ raw string）：

```text
$(end# 注记含 #) 字面 #end)     ← delim="end"
$(tag@ 上下文含 @) 字面 @tag)   ← delim="tag"
```

- 开头 `<delim>#`、结尾 `#<delim>)`——**严格对称**（两侧 marker 须同为 `#` 或 `@`）
- `<delim>` 为 `\w+`；闭合定界符须存在于后续源码，否则整体回落为普通 `$()` 表达式

### 3. 闭合规则

- `${…}` 按 `}`、`$(…)` 按 `)` 闭合——tokenize 增量扫描：字符串/注释感知、括号配平
- 三引号字符串内的换行允许构造跨行；**指令一律单行**

### 4. 空白与独行消除

- 行首/行尾 ASCII 空白（空格/制表符）剥除；`\r` 随行终止符剥离
- **独行消除**：行内全部构造无输出 → 整行（含换行符）移除（指令、纯语句插值、注释、上下文注入行）
- 空行保留（输出 `\n`）；注记行**不**消除（产生输出）

### 5. 插值双形式

| | `${}` 发起型 | `$()` 合并型 |
|---|---|---|
| 冲刷 | 构造即冲刷点 | 从不冲刷 |
| 表达式语句 | 独立 `emit(text(EXPR))`，行号 1:1 | 立即求值暂存 `__pcl_tN`，织入合并段 |
| 纯语句 | 冲刷后原样执行 | 立即执行不打断合并段 |
| 保序 | ✅ 副作用发射与前后文本保序 | 唯一例外：求值期副作用先于同段前置文本落 sink |

- 内容：任意 Python **简单语句**列表（`;` 分隔；复合语句 → C300）
- 表达式语句的值**无条件**经 `text()` 插入（`None` → `null`）；赋值/import 静默执行
- 副作用调用需 `_ =` 前缀丢弃返回值

### 6. 指令集

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
| `${:#}` / `${#}` | 独行 | 丢弃 |

### 7. pass 语义

```
${:pass :read CTX :write SCORE}
<prompt 体：文本、插值——直至下一个指令构造>
```

- prompt 独立 sink（隔离于输出文档）；**遇下一个指令或 EOF 自动提交**（内部 trim）
- `:read` 单变量快照：pass 开始时预序列化冻结；agent 经 `pcl_read` 按名拉取
- `:write` 单变量写回：agent 经 `pcl_write` 写入
  - **自动包装**：唯一授权名 + agent 全部键不在授权列表 → 自动嵌套 `{授权名: {平铺 dict}}`
  - 混合（部分授权 + 部分越权）→ R406
- reply 经 `emit` 追加当前 sink + 存入变量 `reply`
- 空 prompt 跳过（不调桥接）；空回复 → A504；越权写 → R406（先于 A504）
- `:write` 值 JSON 反序列化深度上限 32（R400）
- pass 体内插值不允许 `break`/`continue`/`return`（P203——会跳过自动提交点）

### 8. 上下文管理

- `:save 名` → `名 = save()`：token = opaque 字符串（pi 实现为 sessionFile 路径）；空值 → A501
- `:load 名` → 切换到 token 会话（本地预检文件存在 → 缺失即 R430）
- `:new` → 新建匿名上下文（旧上下文自动落盘保留）
- 跨运行持久化：token 由模板自行存取文件（普通 Python 读写）
- 嵌入形态的会话替换语义见 RFC 0002 §3.7

### 9. 模块与 import

- `.pcl` ≡ Python 模块：加载层 = `:function` 定义 + 顶层 import/字面量赋值；`main(prompt)` = 模板体
- `import pcl; pcl.install_importer()` 后 `import mytpl`；DSL 内 `${import helpers}`
- `.py` 与 `.pcl` 同名时 `.py` 优先；**import 永不触发 agent**

### 10. `text()` 规则

| 类型 | 输出 |
|---|---|
| `str` | 原样 |
| `None` | `null` |
| `bool` | `true` / `false` |
| `int` | 十进制 |
| `float` | round-trip repr |
| `dict/list/tuple` | 紧凑 JSON（`ensure_ascii=False`；tuple 视作 list；键碰撞退化 `str(v)`） |
| 其他 | `str(v)` |

### 11. 保留名

- 运行时保留名（10 个）：`emit` `text` `submit` `save` `load` `new_ctx`
  `push_sink` `pop_sink` `note` `context`——绑定目标同名 → C300
- `:function` 名 `main` / `prompt` / `reply` 保留 → C300
- `__pcl_` 前缀保留

## Revision History

| 修订 | 日期 | 说明 |
|---|---|---|
| r0 | 2026-09-17 | 首稿（含 `$prompt` 裸糖） |
| [r1](rfc-0000-r1-remove-bare-sugar.zh.md) | 2026-09-17 | **移除裸糖** `$prompt` → `$(prompt)`（L103 迁移错误）；构造表相应删行 |

## Error Codes & Exit Codes

| 类 | 码 | 退出码 | 含义 |
|---|---|---|---|
| L | L100–L103 | 1 | 词法（源文件/解码/裸糖迁移） |
| P | P200–P203 | 1 | 解析（块配对/参数/pass 体） |
| C | C300/C305/C310 | 1 | 编译约束（保留名/注释位置/生成源检查） |
| R | R400/R405/R406/R409/R430/R431 | 2 | 运行期（求值/写回/越权/中断/上下文） |
| A | A500–A523 | 3 | 桥接（agent/会话/嵌入） |
| SIGINT | R409 | 130 | 用户中断 |

## Conformance

PCL 实现（编译器 `pclang`）必须满足：

1. 编译产物为**可读 Python 源**，含 `# pcl:N` 行号标注（traceback 回指模板行）
2. 语义等价变换不变式：独行消除不改变输出文档内容；`${}` 副作用保序
3. 错误消息含 `文件:行:列 [码] 消息`（编译期）或码+消息（运行期）
4. 退出码遵守上表

测试套件（`pclang/tests/`）：golden 快照、script 桥逐字节 e2e、
确定性 fuzzer（模板编译不崩溃 + 编译确定性不变式）。

## References

- RFC 0001 — Runtime Definition（执行层契约）
- RFC 0002 — Connector Definition（连接器契约）
- [README.md](../README.md) — 稳定语法面（alpha 期承诺）
