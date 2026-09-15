# pcl — Prompt Control Language

编排 LLM/agent 的模板 DSL：**模板层是 PCL，脚本层是真 Python**。纯 Python 包（≥3.10，零第三方依赖），把 `.pcl` 编译成可读的 Python 源码并在同一解释器中执行，完整复用 Python 生态（含 C 扩展）。首个适配的外部 agent 为 [pi](https://github.com/earendil-works/pi-coding-agent)：拉起 `pi --mode rpc`，经 stdio JSONL 驱动 pcl-connector 扩展完成 pass 交互与上下文管理；反向亦通——连接器在 pi 内注册与 CLI 对齐的 `/pcl` 命令族，`/pcl run f.pcl P` 在当前会话中直接执行（DESIGN.md §8.5/§9.1）。

## 文档

- [docs/DSL.md](docs/DSL.md) — 语言规范 v0.1（已终审）
- [docs/DESIGN.md](docs/DESIGN.md) — 实现设计 v0.1（已终审）

## 一分钟看懂

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

```bash
uvx pclang run demo.pcl "猫为什么会打呼噜"  # 或 pipx install pclang（命令与 import 名仍为 pcl）
```

v0.1 要点：表达式/语句/库全部是 Python——插值双形式 `${}`/`$()`（内容同为任意 Python 简单语句：表达式值插入输出、赋值/`import` 等静默执行，丢弃返回值用 `_ =` 前缀；无 `:py`/`:set`/`:call` 之分）：`${}` 发起型（冲刷保序、表达式独立 emit、行号 1:1）、`$()` 合并型（立即求值、织入所在段落单条 emit）；控制流一律 `:if…:fi` / `:for|:while…:done` 指令对，零 `:` 块语法；缩进无语义（编译剥除行首/行尾空白，源码可自由缩进排版）；裸糖 `$prompt`（文本位置 ≡ `$(prompt)`）= argv 输入 / 函数输入（`${:function NAME(参数列表)}` 复用 Python 形参语法，缺省 `(prompt="")`）；`${:pass :read/:write 名字}` 开启一轮 agent 交互（read/write 各一个名字；prompt 独立 sink 隔离，体为纯输出构造，遇下一指令或 EOF 自动提交），回复进输出文档并存入 `reply`；`${r"""…"""}` 原始三引号字符串（可跨行）输出含 `${` 的大段文本不转义；上下文三指令 `:save`/`:load`/`:new`（`:save cx` 把当前会话的 token 存入变量 `cx`，`:load cx` 取值切换；无映射文件，跨运行把 token 存进自己的文件即可），pass 默认追加当前上下文，压缩信任 agent 自带机制。`.pcl` 即 Python 模块：双向 import 兼容（`import pcl; pcl.install_importer()` 后 `import mytpl as t`；DSL 内 `${import helpers as h}`），import 只执行加载层（定义），永不触发 agent。

状态：v0.1 设计已终审（DSL/DESIGN 冻结，含终审修订、终审复核修订、终审末检修订与终审末轮修订：`:read` 快照 pass 开始预序列化冻结、`pcl run` 插源目录入 `sys.path[0]`、未落盘会话 token `load` 预检 → R430、R406 优先于 A504、reply 落当前 sink/动态嵌套、text() 非字符串键兜底、指令位置违例 P201、生成侧 `\r` 转义保真与非提升位置 `import *` → C300 等），进入实现（M0），尚无可运行代码；终审后补丁已并入（`:read` 冻结值/AnnAssign/`--var` 切分等 + **插值双形式 `${}`/`$()` 定案**、裸糖 `$prompt` 与转义 `$$`）；**终审冻结（last review）修订已并入**（文件末尾孤立 `\r` 剥离、独行消除不触构造吞并的换行、`yield` 放行、无 sessionFile 会话 `:save` → A501——DSL §4.3/§4.4/§7/§13、DESIGN §8.1/§8.3/§11）；**冻结复核（last review）完成**：DSL 双形式残留措辞清理（§4.4/§7/§9.2/§10/§11，语义无变化），DESIGN 无改动，文档正式冻结。
