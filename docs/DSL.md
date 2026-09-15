# PCL 语言规范（Prompt Control Language）

- 状态:v0.1,**终审通过**(终审修订已并入 §4.4/§7/§10/§13;终审复核修订已并入 §2/§4.2/§6/§7/§8/§9.3/§10/§13;终审末检修订已并入 §2/§4.1/§4.4/§6/§7/§10/§11/§12/§13;终审末轮修订已并入 §4.4/§8/§9.1/§9.2/§10/§11/§13;终审后补丁已并入 §7/§9.2/§10(`:read` 冻结转出 JSON-safe 值、注解赋值不提升);**插值双形式定案**(`${}` 发起型:冲刷+独立 emit+保序;`$()` 合并型:立即求值暂存、织入单条 emit、不保序--§2/§4.2/§7/§10,示例随改;**裸糖 `$prompt`**:文本位置 ≡ `$(prompt)`,构造内 `$` 一律 C310,转义 `$$` → `$`);**终审冻结(last review)修订已并入 §4.3/§4.4/§7/§13**--文件末尾孤立 `\r` 随行终止符剥离、独行消除不触及跨行构造吞并的换行、`$$$prompt` 消解示例(§4.3)、`yield` 不入 P203（生成器语义按 Python）；**冻结复核（last review）修订已并入 §4.4/§7/§9.2/§10/§11**——双形式定案残留的单形式枚举清理：pass 体/输出构造/独行消除/P203 措辞补全 `$()`，语义无变化）；实现设计见 [DESIGN.md](DESIGN.md)，里程碑 M0–M4）
- 实现：**纯 Python 包**（`pip`/`pipx`/`uvx` 分发，Python ≥3.10，运行时零第三方依赖）；模板编译器 + 运行时 + agent 桥接均为 Python
- 首个适配的外部 agent：pi（RPC 模式 + pcl-connector 扩展——独立于主包分发，见 DESIGN.md §8–9、§12）；连接器另在 pi 内注册与 CLI 对齐的 `/pcl` 命令族，`/pcl run` 在当前会话中直接执行 PCL（嵌入模式，DESIGN.md §8.5/§9.1）

---

## 1. 定位：双层语言

PCL 只做两件事，其余一切都是 Python：

- **模板层（PCL）**：文本 + `${…}` 构造（指令/插值/注释）。负责输出文档的拼装顺序、pass 的边界、上下文的切换。
- **脚本层（Python）**：所有出现在构造里的代码（条件、表达式、语句）都是 Python，由 PCL 自身的 Python 进程执行（即安装 PCL 的那个解释器）。

程序最终产物 = **输出文档**（stdout / `-o` 文件）+ 副作用（agent 交互、上下文切换、Python 代码自身的任何副作用）。

**非目标**：PCL 自研任何函数库/类型系统/校验体系；并行/多 agent；多行构造（指令与普通插值仍单行；唯一例外：三引号字符串可跨行，§4.2）。

---

## 2. 关键设计决策（评审重点）

| # | 决策 | 理由 |
|---|------|------|
| E1 | PCL 本体是纯 Python 包；`.pcl` 编译生成 Python 源，在同一解释器内执行 | 零嵌入/零 ABI 负担；生成源可读、可缓存（`.pyc`）；生态 = 安装它的解释器 |
| E2 | **插值双形式、内容同构、自动 emit 语义不同**：`${STMTS}`（**发起型**——构造即冲刷点：纯语句先冲刷再执行（保序），每个表达式语句独立 `emit(text(…))`、行号 1:1）与 `$(STMTS)`（**合并型**——立即求值（表达式暂存 `__pcl_tN = text(…)`、行号 1:1）、纯语句不打断，append 进当前合并段单条 emit、从不冲刷）；两者内容均为任意 Python **简单语句列表**（`;` 分隔；表达式语句的值**无条件**经 `text()` 插入（`None` → `null`），赋值/`import`/`del` 等静默执行；无 `:py`/`:set`/`:call` 之分）；副作用丢弃返回值用 `_ =` 前缀；**裸糖 `$prompt`**（文本位置）= 合并型插值 `$(prompt)`（识别：`$` + **完整标识符**恰为 `prompt`——`$prompts` 等其余 `$name` 仍是普通文本，shell 片段/正则不受扰；构造内部不识别 `$`——`${$prompt}`/`$($prompt)` 为非法拼写 → C310；`prompt` 由入口经 `main` 内部形参接收、序言提升为模块全局，§9.2，`pcl run` 以 argv/`--prompt` 传入；函数内 = 形参） | 表达式本就是简单语句的子集；同一内容规则下用**括号**选择发射策略——`${}` 换保序与独立 emit，`$()` 换段落级合并；`$` 仅模板层拼写，语句里写 `prompt` |
| E3 | 控制流指令 1:1 映射 Python 控制流（`if/elif/else…fi`、`while|for…done`、`break/continue`）；块边界 = 指令对；缩进无语义（词法剥除，生成缩进自动插入） | 语法复用最大化；Python 自带语法检查；源码缩进纯为可读性 |
| E4 | `:pass [:read 名字] [:write 名字]`：read = agent 可经 `pcl_read` 拉取的**单个**变量快照（pass 开始即序列化冻结，§7），write = 可经 `pcl_write` 写回的**单个**变量（多值打包进 dict/list 变量）；**reply 存入变量 `reply` 并经 `emit` 自动追加到当前 sink（顶层即输出文档）**，捕获用 `${DRAFT = reply}` | 读/写各一名、能力正交；`:read` 名字在 pass 开始时求值，笔误会被 NameError 抓住 |
| E5 | 上下文三指令 `:save/:load/:new`（`:save` 把当前会话的 **token** 赋给变量，`:load` 取变量值为 token 切换；token 为桥接层生成的 opaque 会话标识）；pass 默认追加当前上下文；无映射文件——跨运行持久化交给普通 Python（§8） | 上下文 = pi 的 session 概念；变量即游标，token 即会话，零自研持久层 |
| E6 | **标准库边界**：PCL 零自研库；可用库 = 安装它的解释器的标准库 + site-packages | 边界一句话说清 |
| E7 | 确定性边界松动：Python 代码可做任何事（文件、网络、时间）；PCL 只保证模板层自身确定 | 宿主即 Python 的固有代价 |
| E8 | 生成代码带 `模板行号映射`；Python 语法错/运行时异常翻译回 `.pcl` 行号 | 可调试性 |
| E9 | 词法规则：独行**无输出构造**整行消除（指令与纯语句插值可混排，§4.4）、**每行行首/行尾空白剥除**（空白 = ASCII 空格/制表符，缩进无语义）、构造闭合为**括号配平**（§4.2）、reply 尾换行折叠（运行期判定，§7）；转义 `$$`（→ 字面 `$`）＋裸糖 `$prompt` | 模板层稳定；缩进自由；闭合规则可通过自身示例（嵌套括号/字典/集合字面量） |
| E10 | 原始文本 = **`${r"""…"""}`**（Python 原始三引号字符串，无专用构造）：内容逐字（不插值、不转义、`\` 字面量）、**可跨行**（PCL 唯一允许跨行的构造情形）；内容含 `"""` 时换 `r'''…'''`，两者都含时拆相邻两段 | 复用 Python 字面量、零新增语法；引号即定界符（C++/Python raw string 惯例）；跨行需求由字符串字面量天然承载 |
| E11 | pass 自动提交：`:pass` 开启专属 prompt sink（隔离于输出文档），体 = 输出构造序列，遇**下一个指令构造**或 EOF 自动提交；体内动态拼装靠插值构造（`${}`/`$()`：表达式与语句） | prompt 边界 = 指令边界，零额外收尾标记；指令先提交后执行，控制流天然无泄漏 |
| E12 | `.pcl` ≡ Python 模块（两相）：加载层 = `:function` + 顶层 import + 字面量赋值；`main(prompt)` = 模板体（global 声明保模块状态）；importer 双向互导入（含 `as`），`.py` 优先 | 与 Python import 生态零摩擦；`pcl run` 行为不变；import 永不触发 agent |

---

## 3. 总览示例

```text
${:# 单轮自评}
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

生成的 Python（示意，`pcl gen` 可查看真品）：

```python
from pcl.runtime import emit, submit, text, push_sink, pop_sink
SCORE = 0                                    # pcl:2  加载层：字面量赋值（import 时执行，§9.2）

def main(__pcl_prompt=""):                   # 模板体入口：其余一切，源序不变（形参经内部名，§9.2）
    global prompt, SCORE, reply              # prompt 序言 + 顶层写回名/reply → 模块全局（§9.2）
    prompt = __pcl_prompt                    # 入口实参提升为模块全局 prompt
    emit("\n")                               # pcl:3  空行（非指令行不消除，§4.4）
    push_sink()                              # pcl:4  :pass 开启 prompt 缓冲（隔离）
    __pcl_t1 = text(prompt)                  # pcl:6  $prompt 裸糖（≡ $(prompt)）：合并型——立即求值暂存（行号 1:1）
    emit("请就以下主题写一段话，并把自评质量分（0..10 整数）写入 SCORE：\n"
         + __pcl_t1 + "\n\n")            # pcl:5-7 合并段：常量+暂存织成单条 emit（冲刷于行 8 指令；尾部随 trim 去除）
    __pcl_buf = pop_sink()                   # pcl:8  遇指令 ${:if}：弹出缓冲（原文，未 trim）
    __pcl_r = submit(__pcl_buf, writes=("SCORE",))   # 自动提交（内部 trim）
    reply = __pcl_r.reply
    if "SCORE" in __pcl_r.writes: SCORE = __pcl_r.writes["SCORE"]   # 未写则保持旧值
    emit(reply + ("\n" if __pcl_buf.endswith("\n") else ""))   # reply 尾换行折叠（运行期判定，§7）
    if SCORE >= 7:                           # pcl:8
        emit("质量达标，结束。\n")
    else:
        emit("分数不够，重写一遍，把新分数写入 SCORE。\n")
```

运行：`pcl run demo.pcl "猫为什么会打呼噜"` ≡ 加载模块 + `main("猫为什么会打呼噜")`（§9.2）。行为：pass 体（含其后的空行）提交（追加到当前上下文）→ agent 回复与 `SCORE` 写回（模块全局）→ 分支输出（注意输出文档以一个空行开头：行 3 的空行不是指令行，不消除；行 7 的空行已随 prompt 提交、尾部 trim 去除）。agent 未写入 `SCORE` 时保持旧值；读取**从未赋值**的名字才会 `NameError`（R400，映射模板行号）。`import demo` 只执行加载层（`SCORE = 0`），不触发 agent、不产出输出。行 6 的 `$prompt` 为**裸糖**（≡ `$(prompt)`，合并型——值织入所在段落的单条 emit，§10）；写作 `${prompt}` 则该处独立成条 `emit(text(prompt))`、段落拆为三条 emit——`${}` 是保序默认。

---

## 4. 词法结构

### 4.1 源文件
UTF-8（文件首的 UTF-8 BOM 剥除；解码失败 → L102），`.pcl` 后缀；首行 `#!` 忽略。

### 4.2 构造与文本
- **文本**：构造以外的一切字节，原样进入输出。
- **插值** `${STMTS}` / `$(STMTS)`：内容均为 Python **简单语句列表**（`;` 分隔；复合语句 → C300）；一般单行，含三引号字符串时可跨行（闭合规则见本节末）；表达式语句的值**无条件**插入（`None` → `null`），其余语句静默执行。两种定界符**内容规则完全同构**，仅**自动 emit 语义不同**（§10）：`${}` 发起型（构造即冲刷点——纯语句先冲刷再执行、表达式独立 `emit(text(…))`）；`$()` 合并型（立即求值、append 进当前合并段，从不冲刷）。指令与注释 `${:#}` 为 `${}` 专属定界（`$()` 无指令形式）。
- **指令**：`${` 之后为 `:` 时进入指令模式，同样按本节闭合规则闭合；**注释** `${:# …}` 例外——行界定（`#` 起至行尾整体丢弃，§4.5），不适用闭合规则。
- **原始文本**：无专用构造——用插值里的 Python 原始字符串 `${r"…"}` / `${r"""…"""}`（三引号形式**可跨行**，是唯一允许跨行的构造情形；跨行部分不参与 §4.4 的剥除/消除）；内容逐字输出（`${`、`\` 均字面量），见 §10。行内单点 `${` 也可用转义 `$${` 或 `${"${"}`。
- `$` 后跟 `{` 或 `(` 进入插值构造；跟**完整标识符 `prompt`** 时为裸糖 `$prompt`（≡ `$(prompt)`，合并型，§10——`$` 取最长标识符，`$prompts` 等其余 `$name` 仍是普通文本）；其余情形 `$` 为普通字符；**字面 `$` 一律 `$$`**（`$${` → `${`、`$$( `→`$(`、`$$prompt` → `$prompt`，§4.3）。

**闭合规则（括号配平）**：自构造开启符起扫描——跳过 Python 字符串字面量的全部形式（单/双/三引号、raw、bytes、f-string）与 `#` 注释（至行尾），并统计括号深度（`(`/`[`/`{` 入、`)`/`]`/`}` 出）；`${…}` 在**深度 0** 遇到首个 `}` 闭合、`$(…)` 在**深度 0** 遇到首个 `)` 闭合（各按自身定界符——`$(D = {"k": 1})` 中 `{}` 只是内容）。因此 `${ {"a": 1} }`、`${n = len(A); m = n * 2; m}`、`${D = {"k": 1}}` 均正确闭合（若构造内出现 `#`，闭合符会被注释吞没至行尾 → 构造无法闭合 → L100/L101；构造内注释请改用独立 `${:# …}` 行。三引号字符串内的换行**允许插值构造**跨行，其余情形构造跨行即未闭合；**指令不享此豁免——仍须单行**，含三引号字符串的指令跨行 → L100）。实现应基于 `tokenize` 做增量扫描，不手写字符串匹配；词法与执行共用同一解释器，tokenize 的方言差异（如 <3.12 解释器遇 PEP 701 f-string）最终由既有错误路径捕获（词法失败 → L100/L101、生成源语法失败 → C310），无需单列规则。

### 4.3 转义
`$$` 产出字面 `$`（自左向右**单遍**成对消解：`$${` → `${`、`$$prompt` → `$prompt`、`$$$$` → `$$`；消解一对 `$$` 后扫描位置右移两位、继续按词法规则识别后续字符——`$$$prompt` → 字面 `$` ＋ 裸糖 `$prompt`（第 3 个 `$` 起仍按规则识别），区别于 `$$prompt` 的整体字面 `$prompt`）；`\` **无任何转义含义**——文本模式的 `\` 是普通字符（raw 字符串内一切原样）。转义**仅在文本模式**（构造之外的文本）识别；构造内部（语句/指令内容）的 `$`/`\` 完全归属 Python 语义。

### 4.4 空白剥除与独行消除

- **构造识别先行**：词法先识别构造（含因三引号字符串而跨行的构造），剥除/消除只作用于构造之外的文本行；构造跨行部分不做任何加工（§4.2）。跨行构造**吞并**的换行（如 raw 三引号字符串内的行尾换行）属构造内容、剥除/消除一概不触及——独行消除仅移除构造之外的本行文本与其行尾换行符，构造已吞并的换行不在此列、无从重复移除。
- **空白剥除**：剥除文本行**行首**与**行尾**的空白——**空白 = ASCII 空格与制表符**（`\r` 不在剥除集内：行按 `\n` 切分，紧邻 `\n` 的 `\r`、以及**文件末尾（其后无任何字符）的行尾孤立 `\r`** 均视为行终止符的一部分随行剥离，故 CRLF 源与 LF 源行为一致、输出换行统一为 `\n`；唯一例外为构造内容逐字——跨行 `${r"""…"""}` 内的 `\r` 属字符串内容、原样保留，§4.2/§10）；全角空格、NBSP 等 Unicode 空白**不算**空白、原样保留。行**中间**的孤立 `\r`（不紧邻 `\n`）不在剥离范围、按内容原样进入输出——「原样」的兑现依赖生成侧**转义保真**：CPython tokenizer 在字符级规范化源码行结束符、不区分是否位于字符串字面量内（`\r\n`/`\r` → `\n`；单/双引号内孤立 `\r` 直接 SyntaxError），故 pygen 发射含 `\r` 的字符串常量时一律退化为非 raw 转义形式（DESIGN §5.2/R21）。源码缩进仅为可读性、**无语义**，不进入输出；生成代码的缩进由块指令结构自动插入。需要输出行首/行尾空白时用 `${" "}` 插值或 `${r"…"}` 原始字符串。
- **独行消除(统一规则)**:剥除后非空、且行内构造(至少一条)**全部为无输出构造**的行 → 整行(含换行符)移除。无输出构造 = 指令、或语句列表不含表达式语句的插值构造(`${}`/`$()` 皆然;指令与纯语句构造可混排--如 `${:fi}${X = 1}`、`${:fi}$(X = 1)` 同行同样消除,不泄漏换行;注释必须独占一行(C305),独行注释行自然消除)。静态可判定--语句列表经 Python 语法拆分即可识别表达式语句之有无。含任何文本或含表达式语句插值（`${}`/`$()`）的行保留（它们产生输出）;剥除后为空的行不含构造,同样保留(输出换行符);文件末行无换行符时照常输出该行、末尾不补换行。

### 4.5 注释
`${:# …}` 至行尾丢弃；必须独占一行（否则 C305）。

---

## 5. 执行模型

1. **编译**：PCL 编译器（纯 Python）解析 `.pcl` → 生成 Python 源（含 pcl:行号标注）。
2. **执行**：生成源为**单模块两相**（§9.2）——加载层（`:function`、顶层 import、字面量赋值）+ 入口 `main`（实参 `prompt`，经内部形参接收并提升为模块全局，§9.2）；`pcl run` = 加载模块 + `main(argv 或 --prompt)`；生成源缓存为 `.pcl.py`（traceback 原生可读，Python 自动复用 `.pyc`）。
3. **输出**：文本/插值（`${}`/`$()`）/pass 回复经 `pcl.runtime` 的 `emit` 写入当前 sink（pass 体内 = prompt 缓冲）；`${}` 独立成条 emit，`$()` 织入所在合并段（发射模型见 §10/DESIGN §5.2——`$()` 求值副作用与同段前置文本的 sink 顺序不保证）。
4. **交互**：`submit()` 阻塞至 agent 空闲，返回 `reply` 与 `writes`（§7）。
5. **错误**：模板层错误（L/P/C）编译期报；生成代码的 Python 语法错误 → C 类（映射行号）；运行时异常 → R 类（traceback 帧逐个映射回 `.pcl` 行）。

---

## 6. 指令参考

通用：`${:动词 …}`，单行闭合。**"位置"列限定允许出现处；位置违例统一 → P201**（`:break`/`:continue` 循环体外、`:return` 函数体外、`:function` 非顶层（含嵌套与控制流块内）、`:elif`/`:else` 未紧跟所属 `:if` 臂等块结构配对类；保留名类仍归 C300，§9.2/§11）。

| 指令 | 位置 | 生成 Python | 说明 |
|---|---|---|---|
| `${:if EXPR}` / `${:elif EXPR}` / `${:else}` / `${:fi}` | 任意 | `if` / `elif` / `else:` 块 | EXPR 为 Python 表达式（truthiness 按 Python 语义） |
| `${:while EXPR}` … `${:done}` | 任意 | `while EXPR:` 块 | 块边界 = 指令对（`:done` 同时终结 `:for`） |
| `${:for X in EXPR}` … `${:done}` | 任意 | `for X in EXPR:` 块 | X 为任意 Python 赋值目标（名字/元组解包），EXPR 为任意 Python 可迭代对象；嵌套循环各自与最近 `${:done}` 配对 |
| `${:break}` / `${:continue}` | 循环体内 | `break` / `continue` | 若紧跟 pass 体之后，先自动提交再跳出（§7）；出现在循环体外 → P201 |
| `${:function NAME[(参数列表)]}` … `${:endfunction}` | 顶层 | `def NAME(参数列表):` 块 | 函数体 = PCL 模板体（可含文本/pass/输出构造）；参数列表为**原样 Python**（多参数、默认值、`*`/`**` 均可），缺省 = `(prompt="")`；函数体内文本位置裸糖 `$prompt` 即插值该形参（§10）。例：`${:function greet(name, times=1)}` → `def greet(name, times=1):` |
| `${:return EXPR}` / `${:return}` | 函数内 | `return (EXPR)` / `return` | 缺省返回 `None`；若紧跟 pass 体之后，先自动提交再返回（§7） |
| `${:pass [:read 名字] [:write 名字]}` | 任意 | §7 生成模式 | agent 交互轮；体 = 输出构造序列，遇下一指令/EOF 自动提交（§7）；体为空 → P202；read/write 各至多一个名字（`:read`/`:write` 标志顺序任意、各至多出现一次；实参须为单个 Python 标识符——写字面量/表达式/属性名 → P200），多值打包进 dict/list 变量 |
| `${:save 名字}` | 任意 | `名字 = save()` | 先终止/提交未决 pass，再把**当前上下文的 token**（opaque str，§8）赋给变量 `名字`（赋值遵循 Python 作用域：顶层 = 模块全局，函数内 = 局部）；实参 = 单个 Python 名字（写字面量/表达式 → P200） |
| `${:load 名字}` | 任意 | `load(名字)` | 取变量 `名字` 的当前值为 token，切换当前上下文到该会话；token 未知/失效（含预检文件不存在，DESIGN §8.3）→ R430 |
| `${:new}` | 任意 | `new_ctx()` | 新建匿名上下文并切换（原上下文若已 `:save` 到某变量，仍可 `:load` 回来） |
| `${:# 注释}` | 独行 | —— | 丢弃 |

指令动词不再是保留标识符（Python 侧任何合法名字均可用）。块体允许为空：`:if`/`:while`/`:for`/`:function` 体为空时生成代码以 `pass` 填充（DESIGN §5.2）。

---

## 7. pass 语义

```
${:pass :read CTX :write SCORE}
<prompt 体：文本、插值（${}/$()）——直至下一个指令构造>
${:return EXPR}     ← 任意 ${:…} 指令（或 EOF）：先自动提交，再执行该指令
```

生成模式（编译器展开；prompt 独立 sink，隔离于输出文档）：

```python
__pcl_reads = {"CTX": __pcl_freeze(CTX)}   # :pass 开始即求值并序列化冻结（先于 push_sink；名字未定义此刻 NameError=R400；
                                           #  body 内重绑定/原地修改均不影响快照——__pcl_freeze 为运行时内部函数，DESIGN §5.2）
push_sink()                                  # :pass 开始，emit 转入 prompt 缓冲
emit("…文本/插值…")                        # 体内只有输出构造，无指令
__pcl_buf = pop_sink()                      # 遇下一指令/EOF：弹出 prompt 缓冲（原文，未 trim）
__pcl_r = submit(__pcl_buf,                 # 自动提交（内部 trim）
            reads=__pcl_reads,
            writes=("SCORE",))
reply = __pcl_r.reply
if "SCORE" in __pcl_r.writes: SCORE = __pcl_r.writes["SCORE"]   # :write 名条件写回；未写则保持旧值
emit(reply + ("\n" if __pcl_buf.endswith("\n") else ""))   # reply 尾换行折叠：提交缓冲 trim 前以换行结尾则补一个（体末为插值时同样正确，运行期判定）
<终止指令生成的语句>                          # :if/:return/:break/:save… 此时已在输出 sink
```

- **自动提交(E11)**:`:pass` 开启 prompt 专属 sink;pass 体 = **纯输出构造序列**（文本、`${}`/`$()`），遇到**下一个指令构造**(任意 `${:...}`,含 `:fi/:else/:done/:endfunction/:return/:break/:continue/:save/:load/:new/:pass`)或模板 EOF 时自动提交。注释在词法期整行消除,不终止 pass(跨行 `${r"""..."""}` 是普通插值构造,同样不终止);相邻 `${:pass}` = 前轮先提交、后轮再开启(*语法*嵌套不可能--pass 体不含指令;经函数调用发生的动态嵌套见 reply 条);体为空 → P202。
- **隔离**:体内一切输出（文本、`${}`/`$()`、`emit`）进入 prompt 缓冲而非输出文档;插值是程序侧渲染,不受 `:read` 约束;`:read` 只管 agent 在 pass 进行中经工具主动拉取。终止指令之前的文本(含空行)也归 prompt,尾部空白随 trim 去除;**行内**指令同样终止 pass(同行其后的文本落入输出文档),建议指令独占一行。
- **trim（提交缓冲）**：`submit` 提交前对缓冲做 **ASCII 空白双端剥除**（空格、`\t`、`\n`、`\r`、`\f`、`\v`——即 §4.4 空白集 ∪ 换行族）；全角空格等 Unicode 空白**不剥**（与 §4.4 哲学一致）——因此仅由全角空白构成的 prompt 不判空、照常提交（空 prompt 跳过按 trim 后判定，见下"失败"）。
- **指令先提交后执行**：终止指令在提交完成**之后**运行——`:break/:continue/:return` 因此天然安全（先提交再跳出，缓冲不泄漏，无 P202 禁令）；要"条件不成立就整轮跳过"时把 pass 包进 `:if`。`:save/:load/:new` 终止 pass 后在输出流中照常生效（后续 pass 落入切换后的上下文）。
- **动态拼装**：体内没有指令——条件/循环只能用插值构造（`${}`/`$()` 均可；三元、`join`、推导式；语句列表的 emit 亦落入 prompt 缓冲；调用含 pass 的模板函数即动态嵌套、合法，见 reply 条）。**静态检查（P203）**：pass 体内插值构造（两种形式）的语句不得为 `break/continue/return`（原样 Python 会跳过自动提交点、泄漏缓冲）；`yield` **不在拦截之列**——`:function` 体内插值含 `yield` 即按 Python 语义把该生成 `def` 变为生成器（调用返回 generator，消费经 `:for`/推导式；main 顶层 `yield` 为语法错 → C310），v0.1 视为合法 Python 语义、不做静态拦截。
- **上下文**：prompt 与回复**默认追加到当前上下文**（§8）；工具调用等中间轮次留在上下文里。
- **写入**：agent 只能写 `:write` 指定的**单个**名字（需要多值就让 agent 写一个 dict/list 变量）；未授权写入由连接器在会话内拒绝（模型当轮重试），漏网者由 `submit` 报 R406。同名多次写，后者胜。`:write` 名不做已定义检查（仅拦截保留名，§9.2）——笔误的后果是写回时悄悄创建该名字。写入值就是 Python 值（JSON 反序列化，深度上限 32、超限 R400），无额外强制转换——需要校验时自己写（例：`${assert 0 <= SCORE <= 10}`）。写回是普通 Python 赋值，**作用域遵循 Python**：顶层 pass 写模块全局名；函数体内的 pass 写该函数的局部名（"未写保持旧值"仅当该作用域中该名已有值，否则后续读取为 UnboundLocalError → R400；跨作用域传递用返回值，见 §12）。
- **读取**：`:read` 指定的**单个**变量在 pass 开始时求值并**即刻按 §10 规则序列化冻结**（生成代码构建的是预序列化的 JSON-safe 值、非持引用——pass 体内 `${}` 对该名的重绑定或**原地修改**（如 `${_ = L.append(9)}`）均不影响 agent 可读到的值；dict/list/tuple → 递归转为**同构 JSON-safe 值**（容器结构保留、非字符串化文本），其余对象退化为 `str()` 字符串值——多值即打包进一个容器变量），agent 在本轮可经连接器的 `pcl_read` 工具按名拉取，其他名字由连接器拒绝。`:read` 与 `:write` 相互独立、互不隐含。快照而非实时读取是架构必然：pass 期间程序阻塞在 `submit()`，既无法应答读取请求，变量也不可能变化。该名字若未定义，pass 开始时即 `NameError`（R400）——`:read` 的笔误天然可被抓（`:write` 不做已定义检查，见上）。
- **reply**：经 `emit` 追加到**当前 sink**（提交点即调用点——顶层 pass 即输出文档），同时存入变量 `reply`（捕获口，如 `${DRAFT = reply}`）；赋值作用域同 `:write` 名——顶层 pass 写模块全局、函数内 pass 写函数局部（见上文"写入"）；不提供输出抑制开关——回复总是落入当前 sink 是默认且唯一行为。**动态嵌套（宏语义的自然延伸）**：pass 体内 `${}` 可调用含 pass 的模板函数（"嵌套不可能"仅指*语法*嵌套，见上）——内层 pass 在 sink 栈上开启自己的缓冲并先行完成一轮提交，其 reply 经 `emit` 落**外层 prompt 缓冲**（外层 prompt 天然拼入内层回复），`:write`/`reply` 写内层函数局部名；静态检查不禁止（P203 只拦 pass 体内直接的 break/continue/return 语句，函数调用不受限）。调用与前后文本的顺序**保序当且仅当用 `${}` 形式**（发起型：构造即冲刷点——pygen 先冲刷合并段、再执行语句/独立 emit，语句位置与值位置皆保序，DESIGN §5.2）；**`$()` 形式**（含 `$(f())` 取返回值、或 `$(SCORE = attempt(prompt))` 语句形式）立即求值但同段文本落 sink 延迟至冲刷点——**求值期间的内层发射（reply 等）会先于同段前置文本落 sink，不保序**；需保序时用 `${}`。
- **失败**：桥接层超时/崩溃/协议错误 → A5xx，程序终止（退出码 3）。**空回复**（agent 仅调用 `pcl_write` 而无文本、或轮次被中止）→ A504——宁报错不静默；越权写（R406）与空回复并存时 **R406 优先**（先报越权，DESIGN §6）。需要「只写不语」的 pass（agent 仅回填结构化值）时，在 prompt 中要求 agent 同时回复一句任意短文本、或把值放进回复由 `${…}` 自行解析——否则 write-only pass 将确定性触发 A504。**空 prompt 跳过**：body 渲染后 trim 为空（如仅空行或 `${""}`）→ `submit` **不调桥接层**，返回空结果（`reply` 赋空串、无写回；折叠换行的情形会产出一个空行——空 prompt 多为模板缺陷）；P202 只查"体为空"这一静态情形。
- pass 可出现在函数体内（调用时交互，reply 发往调用点 sink——宏语义；调用点若在另一 pass 体内，则落该外层 prompt 缓冲，即 reply 条"动态嵌套"）；函数内的 pass 通常由 `${:return}` 或 `${:endfunction}` 终止（先提交、写回，再返回）。

---

## 8. 上下文（context / 会话 token）

- **当前上下文**：程序启动时为一个匿名新上下文（对应一个 agent 会话）。pass 默认追加其中。嵌入形态（pi 内 `/pcl run`，DESIGN §8.5）例外：启动上下文 = 宿主 pi 的当前会话——pass 直接续写在用户正在对话的上下文里，`:save` 取得的 token 即该会话（宿主会话尚未落盘、无 sessionFile 时 `:save` 判为 A501——宁报错不返回空 token，DESIGN §8.6）；嵌入形态的 `:new`/`:load` 经模块级桥接接续支持（会话替换或用户切换会话时，运行自动跟随新会话；失败 → A520–A523，见 DESIGN §8.6）。
- `${:save 名字}`：先照常终止/提交未决 pass，再把**当前上下文的 token**（桥接层生成的会话标识，opaque str，见 DESIGN §8.3）**赋给变量 `名字`**——变量即上下文游标，可在同一程序内随时 `${:load 名字}` 切换回来。实参 = 单个 Python 名字（写字面量/表达式 → P200）；赋值遵循 Python 作用域（顶层 = 模块全局，函数内 = 局部）；重复 save 覆盖变量旧值。
- `${:load 名字}`：取变量 `名字` 的当前值为 token，切换当前上下文到该会话；后续 pass 在该会话中继续（模型看得到历史）。token 未知/失效（如 session 文件已删、**或尚未落盘**——pi 的会话文件在首个 assistant 回复后才写盘，`:save` 早于任何 pass 时 token 指向尚不存在的文件，DESIGN §8.3 以 load 前文件存在性预检拦为 R430）→ R430；变量未定义 → NameError（R400），值非 str → R431。
- `${:new}`：切换到全新匿名上下文（原上下文若已 `:save` 到某变量，仍可 `:load` 回来）。
- **跨运行持久化**：token 本身即会话标识（会话数据落在 agent 自己的 session 存储），PCL **不维护任何映射文件**——需要跨运行续聊时用普通 Python 把 token 存取到自己的文件：

```text
${:save cx}
${_ = open("ctx.txt", "w").write(cx)}     ← write 返回字符数，用 _ = 丢弃

（下次运行）
${cx = open("ctx.txt").read().strip()}
${:load cx}
```

- **压缩**：上下文无限增长由 agent 自带机制处理（pi 自动 compaction）；PCL 不提供任何压缩/裁剪指令。

---

## 9. 标准库边界、模块与 import

### 9.1 标准库边界

- **PCL 自身提供的全部运行时设施**：模板指令（§6）+ `pcl.runtime` 模块（`emit/text/submit/save/load/new_ctx`，均为 PCL 机制而非通用函数库）+ importer（§9.3）+ 内置变量 `prompt`/`reply`。插值构造（`${}`/`$()`）里直接调用这些运行时函数（如 `${_ = submit("…")}`——保留名仅拦绑定目标、不拦调用）属**未承诺行为**：绕过 `:pass` 的协议注入与静态检查（P202/P203），正确性与兼容性不保证（v0.1 不禁用）。
- **其余一切**：安装 PCL 的那个解释器的标准库与其 site-packages（含 C 扩展），通过 `${import …}` 使用。
- PCL 永不自研 math/文件/字符串等库；版本与可用包 = 该解释器自身。

### 9.2 模块语义：加载层与 `main`

`.pcl` 的编译产物是**一个普通 Python 模块**，分两相（单一产物，`pcl run` 与 `import` 共用）：

- **加载层**（import 时执行，按源序）：顶层 `:function` 定义；顶层插值构造（`${}`/`$()`）中**整体为 import / 字面量赋值**的语句列表（静态判定：语句列表中**每条语句**均为 import 或字面量赋值，二者可混排；字面量赋值 = RHS 为字面量、纯字面量容器，或数值字面量的一元 `+`/`-`/`~`——`X = -5` 提升、`X = 1+2` 不提升、注解赋值（如 `${X: int = 5}`）不提升（仅普通 `=` 赋值参与提升，注解赋值照常留在 `main`）；绑定目标为简单名、`as` 别名或元组解包均可）。其余顶层插值构造不提升（如 `${DRAFT = reply}` 依赖模板体结果，自然留在 `main`）。`import *`（`from … import *`）仅在**可提升**的语句列表中支持——Python 禁止函数内 `import *`，且 `*` 绑定名不可静态枚举、无法经 global 声明落模块全局；不提升的插值构造（`${}`/`$()`；混排其他语句、或位于 `:if` 块/`:function` 体内等非顶层处）含 `import *` → C300。
- **`main(__pcl_prompt="")`(prompt 序言)**:其余一切模板构造（文本/`${}`/`$()`（含跨行 raw 字符串）/pass/控制流块）,**源序不变**;输出经 `emit` 流入 Run 的输出 sink,**main 无返回值约定**(库形态从 `run.result()` 取,DESIGN §6)。函数首先**恒发射序言** `global prompt` + `prompt = __pcl_prompt`--入口实参经内部形参接收、就地提升为**模块全局** `prompt`:它是普通模块全局名,`${prompt = ...}` 等绑定照常写入(形参若直接命名 `prompt`,`global prompt` 与形参同名 → Python 语法错,故经内部名中转;`:function` 的形参无 global 机制、不受影响,仍是普通 Python 形参)。`prompt` 已单独声明,不参与下列并集。main 对下列名字的**并集**生成 `global` 声明:`reply`、**main 内(`:function` 体外、任意嵌套深度)pass 的 `:write` 名**、以及 main 内(`:function` 体外)的一切**绑定目标**--赋值(含增强赋值与 walrus `:=`--含推导式内 NamedExpr:PEP 572 使其绑定包含作用域,需一并计入)、`:for` 循环变量、`:save` 目标、`import` 绑定名、`del` 目标(含嵌套控制流块;对提升到加载层的名字声明与否等价,超集无害)--模板顶层名字一律模块全局,模块状态语义与单流执行一致(§7 作用域、§12 终态)。
- `pcl run f.pcl P` ≡ 加载 f 模块 + `main(P)`；输出/退出码/错误码不变。
- **import 永不运行模板体**（不触发 agent、不产出输出）——与 Python 的唯一刻意偏差（`emit`/`submit` 依赖 Run）。
- 保留名：`main`/`prompt`/`reply`（三者**仅作为 `:function` 名**保留 → C300——`main` 为入口名；`prompt`/`reply` 在 main 中恒经 `global` 声明、被序言（`prompt`）/顶层 pass 写回（`reply`）赋为模块全局，模块级同名 `def` 会在运行中被静默覆写；作为普通绑定目标（赋值、`:write`/`:save`/`:for` 名等）**不保留**——这些写发生在序言之后、遵循源序语义）、运行时名 `emit`/`text`/`submit`/`save`/`load`/`new_ctx`/`push_sink`/`pop_sink`（**8 名一律保留，无论本模块生成代码是否用到**；生成头部按需导入它们——用户侧任何绑定目标：赋值（含 walrus）、`:function` 名与形参、`:for`/`:save`/`:write` 名、`import … as`、`del`——与之同名 → C300，防止毒化生成调用）与 `__pcl_` 前缀；模块附带 `__pcl_source__`（源路径）。

### 9.3 import 互操作（含 `as`）

| 方向 | 写法 | 机制 |
|---|---|---|
| DSL → Python | `${import json}`、`${import numpy as np}`、`${from pkg import m as n}` | `${}` 原样 Python 语句 |
| DSL → DSL | `${import helpers as h}` | importer 解析 `helpers.pcl`（`pcl run` 内建安装；加载层只执行其定义） |
| Python → DSL | `import pcl; pcl.install_importer()` 后 `import mytpl as t`、`from mytpl import greet as g`；或免装 hook 的 `pcl.import_module("mytpl")` | FileFinder(`.pcl`) → 编译缓存（sha 失配重生成，同 DESIGN A11）→ exec 加载层 |
| Python → Python | 原生 | — |

- `as`（模块/成员别名）两侧均为 Python 原生语法/机制，importer 零额外成本。
- **入口路径**：`pcl run` / `run_program` 把入口 `.pcl` 所在目录（realpath 解析后）插入 `sys.path[0]`（幂等，对齐 `python script.py`），`${import helpers}` 由此解析同目录库；`install_importer` 只注册 hook、不改 `sys.path`（库形态自行决定路径）。
- 生成的模块其 `__file__`/`__package__`/`__path__` 按**源 `.pcl` 位置**设置（代码来自缓存文件，见 DESIGN §5.3），因此 `.pcl` 内的**相对 import** 按源目录解析，与 `.py` 行为一致。
- 同名 `.py` 与 `.pcl` 并存时 **`.py` 优先**（hook 追加注册，不遮蔽既有 Python）；被导入 `.pcl` 的编译错误以 `ImportError` 上报（附原始 L/P/C 诊断）；循环导入遵循 Python 语义。
- 库模块示例：

```text
# greet.pcl（库：加载层即可用）
${from string import capwords as titlecase}
${GREETING = "hello"}
${:function greet}
$(titlecase(GREETING)), $prompt!
${:endfunction}
```

```python
import pcl; pcl.install_importer()
from greet import greet as hello      # Python → DSL（含 as）
with pcl.Run(agent="null") as r:      # emit 需 Run 上下文（无 Run 时调用 → R405，DESIGN §6）
    hello("pcl")                      # 输出 "Hello, pcl!\n" 至 r 的输出
```

```text
${from greet import greet as hello}
${_ = hello("world")}                  ← DSL → DSL（丢弃返回值；要取返回值赋给变量，如 `${g = hello("world")}`）
```

---

## 10. 插值与 `text()`

文本位置的输出构造 = 插值双形式 `${}`/`$()`（§4.2；独行消除中含表达式语句的插值——两种形式——视为“产生输出”、所在行不消除；行内全部构造均无输出时整行消除，§4.4）。原始大段文本用插值构造承载 Python 原始三引号字符串：

- `${STMTS}` / `$(STMTS)`：**插值双形式**——内容规则完全同构：执行 Python **简单语句列表**（`;` 分隔；一般单行，含三引号字符串时可跨行，§4.2）。**复合语句不允许**——控制流一律用指令对（`:if/:fi`、`:for/:done`、`:while/:done`），模板层不暴露 Python 的 `:` 块语法与缩进（含复合语句 → C300，两种形式同规）。`return`/`break`/`continue` 本身是简单语句：在 `:function` 体/循环体的插值构造里原样合法、与 `:return`/`:break`/`:continue` 指令冗余并存（推荐指令形式）；pass 体内则被 P203 静态禁止（§7，两种形式同规）。插入规则：语句序列中的每个**表达式语句**求值后**无条件**按序经 `text()` 插入当前 sink（pass 体内即 prompt；`None` → `null`）；赋值、`import`、`del`、`assert` 等语句只执行、不插入（`${SCORE = 0}`、`${import os}`）。因此**一切副作用调用都要 `_ =` 前缀**（`${_ = subprocess.run(cmd)}`）——不带前缀时返回值（含 `None`）会被插入：`${sorted(x)}` 插入结果列表，`${emit("x")}` 在输出 `x` 后再插入一行 `null`。**裸糖 `$prompt`（文本位置）≡ `$(prompt)`**：`$` 取最长标识符、恰为 `prompt` 时即合并型插值该名（其余 `$name` 为普通文本；字面 `$` 一律 `$$`，§4.3）；**构造内部不识别 `$`**——`${$prompt}`/`$($prompt)` 为非法拼写（`$` 在 Python 侧即语法错 → C310），发起型写 `${prompt}`；`${None}`/`$(None)` 输出 `null`。插值不产生任何交互——不触发提交，也不是指令（不终止 pass 体）；**空语句列表（两种形式）合法、为无操作**（所在行按独行消除规则处理，§4.4）。
- **发射语义按定界符（自动 emit，DESIGN §5.2）**：`${}` = **发起型**——构造即冲刷点：进入构造先把当前合并段织成一条 emit，纯语句随后原样执行（副作用发射与前后文本**保序**），每个表达式语句**独立成条** `emit(text(EXPR))`（生成行号与构造行 1:1，E8 归因精确；不与前后合并）。`$()` = **合并型**——从不冲刷：表达式语句**立即求值**暂存（生成 `__pcl_tN = text(EXPR)`，行号 1:1、源序求值）并把暂存引用 append 进合并段，纯语句原样立即执行、不打断合并段；段在下一冲刷点（`${}` 构造/指令/pass 冻结与开闭提交/reply 发射/EOF）织成**单条** `emit("常量" + __pcl_tN + "常量" …)`。`$()` 求值顺序即源序（暂存即时）；**唯一不保证**：求值期间的发射副作用（如以 `$(f())` 取含 pass 函数的返回值、或 `$(SCORE = attempt(prompt))` 语句形式）会**先于同段未冲刷的前置文本**落 sink——需保序改用 `${}`。两种形式的 C310/R400 均归因到各自构造行（独立 emit 行/暂存行；合并段仅拼常量与暂存引用、不含用户代码求值）。例：`${n = len(A); n * 2}`（语句执行 + 末尾表达式独立 emit）；`第 $(i) 次`（织入段落单条 emit）；循环渲染用指令对内联：`${:for s in HISTORY}- $(s)` 换行 `${:done}`（循环体每轮输出 `- 值\n` 单条 emit，`:done` 行整行消除）。
- `${r"""…"""}`（或 `r'''…'''`；两种定界符均可，`$(r"""…"""`)` 同理）：**原始文本**——就是 Python 原始三引号字符串（PCL 无专用原始段构造）：内容逐字（不插值、不转义、`\` 为字面量；含 `\r` 的逐字输出由生成侧转义保真兑现——DESIGN §5.2/R21），**可跨行**（唯一允许跨行的构造形式，跨行部分不参与剥除/消除，§4.4）；作为表达式语句经 `text()` 输出（str → 原样）。内容需含 `"""` 时用 `r'''…'''`（反之亦然）；两种引号序列都含时拆成相邻两段（输出相接）。例：

  ```text
  ${r"""请按 ${变量} 格式输出，示例：${EXPR}——本行 ${ 与 \ 均原样"""}
  ${r"""
  int main() {
      return 0;   // 缩进与换行原样
  }"""}
  ```

  输出：`请按 ${变量} 格式输出，示例：${EXPR}——本行 ${ 与 \ 均原样`，以及一个三行 C 代码块（换行、缩进完全保留）

`text(v)` 规则：`str` → 原样；`dict/list/tuple` → 紧凑 JSON（`ensure_ascii=False`，键按插入序，tuple 视作 list，非字符串键中 int/float/bool/None 按 JSON 惯例字符串化、其余（如 tuple 键）以 `str()` 兜底后作键（与容器内不可 JSON 化的值同路）；键字符串化后碰撞（如 `1` 与 `"1"`、或 `(1,2)` 与 `"(1,2)"`）视作整体序列化失败（退化为 `str(v)`，避免产出重复键）；**容器内不可 JSON 化的值与 `NaN`/`Infinity` 以 `str()` 兜底，整体序列化失败（如循环引用）退化为 `str(v)`**）；`bool` → `true/false`；`None` → `null`；`int` → 十进制；`float` → round-trip repr；其余对象 → `str(v)`。`:read` 快照按同套规则转出 **JSON-safe 值**（容器结构保留、非文本，§7）且在 **pass 开始一次完成**（冻结——后续重绑定/原地修改不影响），`NaN`/`Infinity` 无论在容器内还是**顶层**均先 `str()` 兜底、作为 JSON 字符串值下发（保证发往连接器的 JSON 严格合法）。

---

## 11. 错误与退出码

格式 `file.pcl:行:列 [CODE] 消息`（Python 侧错误映射到模板行号）。

| 类 | 码 | 含义 |
|----|----|------|
| L | L100–L102 | 构造未闭合（含非法跨行）；`${` 后非法内容；词法错误 |
| P | P200-P203 | 指令语法错误;块结构配对错误(含位置违例,§6:break/continue 循环外、return 函数外、function 非顶层(含嵌套)、elif/else 错位);pass 块为空;pass 体内插值（`${}`/`$()`）的 break/continue/return |
| C | C300 | 模板层语义错误（注释未独行（C305）、`:function main/prompt/reply` 保留名（§9.2）、运行时保留名绑定（§9.2）、插值构造（`${}`/`$()`）含复合语句、非提升位置的 `import *`（§9.2）等；`:function` 嵌套/非顶层归 P201，§6） |
| | C310 | 生成代码未通过 Python 编译（内嵌表达式/语句语法错误，映射行号后报告） |
| R | R400 | 运行时 Python 异常（含 NameError 等，附原 traceback 摘要）；写回值 JSON 反序列化深度 >32（DESIGN §6） |
| | R405 | 运行时函数在无 `Run` 上下文处调用（`emit`/`submit`/`save`/`load`/`new_ctx` 于 `with Run` 之外，如 import 后直接调用模板函数） |
| | R406 | agent 写 `:write` 之外的名字 |
| | R409 | 用户中断 |
| | R430/R431 | `:load` token 未知/失效 / 变量值非 str |
| A | A500–A504 | agent 启动失败/协议错误/超时/异常退出/无有效回复 |
| | A510 | script 桥回放耗尽（`--agent script` 专用，见 DESIGN §7） |
| | A520 | 嵌入模式（pi 内 `/pcl run`）下旧版连接器拒绝 `:new`/`:load`（`embed-ctx-unsupported`，版本深移护栏；接续见 DESIGN §8.6） |
| | A521/A522/A523 | 嵌入接续失败（DESIGN §8.6）：孤儿（替换后无实例在时限内接管，如跨 cwd 切换/扩展 reload；仅当 pcl 有在途命令，空闲时以 A503 呈现）/ `:load` 目标 cwd ≠ 当前（引导走正向 CLI）/ auto-follow 降级绑定无会话控制权（执行任一 `/pcl` 命令恢复或改用正向 CLI） |

退出码：`0` 成功；`1` 编译期（L/P/C）与用法错（argparse 默认 2 覆写为 1——用法错属"未开始执行"，与编译期同类，避免与运行期冲突，DESIGN §10）；`2` 运行期（R）；`3` 桥接（A）；`130` SIGINT。

---

## 12. 完整示例：函数化重写循环 + 上下文

```text
${from math import floor}

${SCORE = 0}
${HISTORY = []}

${:function attempt}
    ${:pass :write SCORE}
        请就以下主题写一段话（第 $(len(HISTORY) + 1) 次尝试），完成后调用 pcl_write 把自评质量分（0..10 整数）写入 SCORE：
        $prompt
    ${:return SCORE}
${:endfunction}

${:save cx}
${:while SCORE < 7 and len(HISTORY) < 5}
    ${SCORE = attempt(prompt)}
    ${_ = HISTORY.append(SCORE)}
${:done}

历史得分：
${:for s in HISTORY}
    - $(s)
${:done}
平均（去尾）：$(floor(sum(HISTORY) / len(HISTORY)))

${:# 换一个干净上下文做摘要}
${:new}
${:pass :read HISTORY}
    请把当前得分历史总结成一句话；数据请调用 pcl_read 读取 HISTORY。
```

要点：`attempt` 是含 pass 的模板函数（缺省形参 `prompt`；pass 体由 `${:return SCORE}` 终止——先自动提交、写回**函数局部** SCORE（§7 作用域规则），再返回），分数经 `:return` 带出、由循环体 `${SCORE = attempt(prompt)}` 赋回全局，while 条件因此读得到新值（注意：agent 未调 `pcl_write` 时 `attempt` 内 `SCORE` 从未被赋值，`:return SCORE` 将 UnboundLocalError（R400，§7 作用域规则）——需要防呆时在函数体内先 `${SCORE = 0}` 初始化局部）；`prompt` 既是顶层输入又是函数形参；列表操作/`math.floor` 全为 Python；历史得分用 `:for`…`:done` 指令对渲染（块由指令对分割，零 `:` 块语法）；行内值插值一律 `$()`（裸糖 `$prompt` 同为其一——立即求值、织入段落单条 emit），语句与含 pass 的调用保持 `${}`（发起型冲刷保序，§10）；本示例以 4 空格缩进区隔嵌套块——**缩进无语义**（词法剥除行首/行尾空白，§4.4；生成代码缩进自动插入），平铺写法（如 §3）同样合法；每次 `attempt()` 的回复按宏语义发往调用点 sink，即各轮草稿也会进入输出文档（回复总是落当前 sink——此处调用点在输出流，§7）；`${:save cx}` 把主循环上下文的 token 存入 `cx`（`:save` 生成会话标识赋给变量、`:load` 取值切换，§8），`:new` 后开新上下文做摘要（两边互不污染；S0 仍可经 `cx` 续聊）；摘要 pass 用 `:read` 让 agent 按需拉取 HISTORY（长内容不必拼进 prompt）。

运行：`pcl run rewrite.pcl "为什么天空是蓝色的"`。

### 12.1 一次执行的 trace

`pcl run rewrite.pcl "为什么天空是蓝色的"`（桥 = pi）。假设 agent 行为：第 1 次尝试自评 5 分（不达标）、第 2 次 8 分（达标）；摘要轮先 `pcl_read` 再作答。下文"行 N" = 模板行号（生成源中的 `# pcl:N`）；⇢ = 与 pi 子进程的桥接交互（完整时序见 DESIGN §8.2）。

**编译期**（毫秒级，不涉 agent）：`rewrite.pcl` → 生成并落地 `rewrite-<sha8>.pcl.py`（缓存根 = `$XDG_CACHE_HOME` 缺省 `~/.cache` 下的 `pcl/`，DESIGN §5.3），无 L/P/C 错误；再次运行命中缓存（Python 侧自动复用 `.pyc`）。

**运行期**：

1. **模块加载层**（§9.2，import 期执行）：行 1 `from math import floor`；行 3–4 `SCORE = 0`、`HISTORY = []`（字面量赋值，提升）；行 6–11 `def attempt`（缺省形参 `prompt=""`；其 pass 体 = 行 8–9，将由行 10 `${:return SCORE}` 终止）。当前上下文 = 启动即建的匿名会话 **S0**。
2. `main("为什么天空是蓝色的")`：序言把入口实参提升为模块全局 `prompt`（§9.2），开始执行模板体（源序）：行 2/5/12（空行——独行消除只删无输出构造行、不删空行）：输出文档 = `"\n\n\n"`。
3. 行 13：`cx = save()`——桥接层返回当前会话 S0 的 **token**（opaque str），赋给模块全局 `cx`（无映射文件；pi 侧先 `set_session_name("pcl:" + token 的 basename 去扩展名)` 便于 /resume 辨识（token 为绝对路径，目录前缀对全体会话相同、取前 8 位无法区分，故取 basename）、**再重取 `get_state` 以末次 `sessionFile` 为 token**——改名若轮转会话文件、token 仍指向现路径（embed 形态跳过命名），见 DESIGN §8.3）；此后可 `${:load cx}` 切回 S0。
4. 行 14 判定 `0 < 7 and 0 < 5` → 进入循环；行 15 调用 `attempt("为什么天空是蓝色的")`：
   - `push_sink()`：函数体内 emit 转入 prompt 缓冲（与输出文档隔离）；
   - 行 8–9 渲染入缓冲（此刻 `HISTORY == []`；行首 8 空格缩进已剥除，§4.4）：`请就以下主题写一段话（第 1 次尝试）…写入 SCORE：\n` + `为什么天空是蓝色的\n`；
   - 行 10 **遇指令 `${:return SCORE}` → 自动提交**（`__pcl_buf = pop_sink()` → `submit(__pcl_buf, writes=("SCORE",))`，§7；本例无 `:read`，`reads` 实参省略——无 read/write 时对应 Python 实参不发射，信令层三键恒出现，DESIGN §6/§8.2）。**提交 prompt①**（trim 后——尾部空行随 trim 去除；追加到 S0 → LLM，注入 pcl_write 用法）：

     ```text
     请就以下主题写一段话（第 1 次尝试），完成后调用 pcl_write 把自评质量分（0..10 整数）写入 SCORE：
     为什么天空是蓝色的
     ```

     ⇢ `/pcl pass {"writable":["SCORE"],"reads":{},"text":…}`（连接器登记 write 名单并经 sendUserMessage 入会话，text = prompt① 全文）；
     ⇢ `tool_execution_start(pcl_write {"SCORE": 5})`（写值随事件回流主机）；
     ⇢ `agent_settled` → `get_last_assistant_text` → **草稿1**；
   - 写回**函数局部** `SCORE = 5`（作用域见 §7）；`emit(草稿1 + "\n")` 落到调用点 sink（输出文档）；
   - 提交完成后才执行 `return 5` → 行 15 赋回全局 `SCORE = 5`，行 16 `_ = HISTORY.append(5)`（返回值丢弃、整行消除，`HISTORY = [5]`）。
5. 行 14 判定 `5 < 7` → 第 2 轮：同 `attempt()` 流程（此刻 `HISTORY == [5]`，prompt 中 `len(HISTORY)+1` = 2）。**提交 prompt②**（trim 后，追加到 S0）：

   ```text
   请就以下主题写一段话（第 2 次尝试），完成后调用 pcl_write 把自评质量分（0..10 整数）写入 SCORE：
   为什么天空是蓝色的
   ```

   ⇢ `pcl_write {"SCORE": 8}`（写回）→ **草稿2**；`return 8` → 全局 `SCORE = 8`、`HISTORY = [5, 8]`；输出文档 += `草稿2\n`。
6. 行 14 判定 `8 < 7` 为假 → 退出循环（共 2 轮，未触及 5 轮上限）。
7. 行 18–24：空行；`历史得分：\n`；行 20 `${:for s in HISTORY}` 开循环——循环体 = 行 21 `- $(s)`＋行尾换行（行首缩进已剥除），两轮各输出 `- 5\n`、`- 8\n`（插值经 `text()`）；行 22 `${:done}` 整行消除；行 23 `$(floor(13/2))` → `6`；行 24 空行。
8. 行 25（注释，整行消除）；行 26 `new_ctx()`：切换到新匿名会话 **S1**（S0 的 token 仍在 `cx` 里；上下文切换不影响 Python 名字空间，`HISTORY` 照常可读）。
9. 行 27–28 摘要 pass：**模板 EOF 触发自动提交**（`__pcl_buf = pop_sink()` → `submit(__pcl_buf, reads=__pcl_reads)`，§7）（快照 `{"HISTORY": [5, 8]}` 已在 `:pass` 开始时构建并序列化冻结，§7；无 `:write`，`writes` 省略；行首缩进已剥除）。**提交 prompt③**（trim 后，追加到 S1）：

   ```text
   请把当前得分历史总结成一句话；数据请调用 pcl_read 读取 HISTORY。
   ```

    ⇢ `/pcl pass {"writable":[],"reads":{"HISTORY":[5,8]},"text":…}`（`:read` 快照在 pass 开始按 §10 规则序列化；无 `:write`，连接器不注入 pcl_write 协议；text = prompt③ 全文）；
    ⇢ agent 调 `pcl_read {"names":["HISTORY"]}` → 连接器查快照**本地应答** `{"HISTORY":[5,8]}`（不经主机往返）；
    ⇢ `agent_settled` → **摘要文本**；
    随后 `reply` = 摘要，`emit(摘要 + "\n")`。
10. 模板 EOF：pi 子进程关闭，退出码 **0**。（`--trace` 时第 4/5/9 步还会把 `message_update` 增量转发到 stderr。）

**输出文档**（stdout / `-o`；`←` 起为标注、非实际内容）：

```text
                           ← 行 2、5、12 的三个空行
草稿1 正文……               ← 第 1 轮 reply（宏语义落到调用点 sink）
草稿2 正文……               ← 第 2 轮 reply
                           ← 行 18 空行
历史得分：                  ← 行 19
- 5
- 8                        ← 行 21：循环体（两轮迭代，行首缩进剥除）
平均（去尾）：6             ← 行 23：floor(13/2)（行 22 :done 整行消除）
                           ← 行 24 空行
两次自评 5 与 8，第 2 轮达标（均分 6.5）。   ← 摘要 pass 的 reply
```

**会话提交记录**（本次运行向各会话追加的内容概览；`←` = 提交的 prompt，`→` = agent 侧动作）：

```text
S0（token 存于模块全局 cx）
  ← prompt① 请就以下主题写一段话（第 1 次尝试），完成后调用 pcl_write 把自评质量分（0..10 整数）写入 SCORE：
         为什么天空是蓝色的
  → 草稿1 ＋ pcl_write {"SCORE": 5}
  ← prompt② 请就以下主题写一段话（第 2 次尝试），完成后调用 pcl_write 把自评质量分（0..10 整数）写入 SCORE：
         为什么天空是蓝色的
  → 草稿2 ＋ pcl_write {"SCORE": 8}
S1（匿名会话）
  ← prompt③ 请把当前得分历史总结成一句话；数据请调用 pcl_read 读取 HISTORY。
  → pcl_read {"names":["HISTORY"]}（连接器本地应答 {"HISTORY":[5,8]}）＋ 摘要文本
```

**终态**：模块全局 `cx` = S0 的 token（S0 含两轮尝试及 pcl_write 工具轮；同进程内 `${:load cx}`、或跨运行把 token 存回文件后 `${:load cx}` 即可续聊，见 §8）；S1 为匿名会话、含摘要轮；进程内模块全局 `SCORE=8`、`HISTORY=[5,8]`、`reply`=摘要（main 的 global 声明，§9.2）。同一行为可用 `--agent script` 回放（固定 `{reply, writes}` 序列）对输出文档做逐字节断言（DESIGN §11 e2e-script）。

---

## 13. 非目标与未来方向（备忘）

多行构造（指令与普通插值仍单行；唯一例外：三引号字符串可跨行）、并行/多 agent、其他 agent 工具适配子包、生成源码的 `.pyc` 级缓存开关。

**v0.1 评审已决**：`text()` 规则如 §10（JSON + `str()` 兜底）；回复无输出抑制开关；上下文跨运行持久化不内置（token 交用户保管）；不引入多行 Python（复杂逻辑写 `.py` 再 import）；`:read`/`:write` 各限一个名字、`:write` 不做已定义检查（保留名除外）；原始文本 = `${r"""…"""}`（Python 原始三引号字符串、可跨行；无专用构造）；`${}` 表达式语句无条件插入（`None` → `null`）；加载层提升判据维持"字面量赋值/import"；运行时名（`emit`/`text`/`submit`/`save`/`load`/`new_ctx`/`push_sink`/`pop_sink`）列为保留名（任何绑定目标 → C300）；**终审追加**：`:function` 名 `prompt`/`reply` 保留（→ C300；作为普通绑定目标不保留——序言/pass 写回只与模块级 `def` 结构性冲突）；独行消除统一为"行内全部构造无输出即消除"（指令与纯语句 `${}` 可混排，不再泄漏混排行换行）；submit trim = ASCII 空白双端剥除（全角空白不剥、不判空）；**终审修订**：`text()` 键字符串化碰撞 → 整体退化 `str(v)`（§10）；文件末行无换行照常输出、不补换行（§4.4）；write-only pass 维持 A504、推荐 prompt 要求 agent 附短文本（§7）；`:save` 命名次序与 embed 跳过重命名、reply 兜底缓存每 pass 重置、`run_program` 模块实例隔离见 DESIGN §8.3/§8.1–8.2/§6；**终审复核追加**：`:read` 快照在 pass 开始按 §10 规则**预序列化冻结**（重绑定/原地修改均不影响，§7）；`pcl run`/`run_program` 插入口 `.pcl` 所在目录入 `sys.path[0]`（§9.3）；`:load` 前预检 token 文件存在性——未落盘会话（pi 首个 assistant 回复后才写盘）→ R430（§8，DESIGN §8.3/R20）；越权写 R406 优先于空回复 A504（§7）；`:read`/`:write` 实参须为单个标识符（否则 P200）、`:break`/`:continue` 循环外 → P201（§6）；`--var` 名须为合法 Python 标识符（DESIGN §6）；**终审末检追加**：reply 经 `emit` 落**当前 sink**（调用点；顶层即输出文档）——pass 体内 `${}` 调用含 pass 的函数之**动态嵌套**受支持、内层 reply 落外层 prompt 缓冲（§7）；`text()` 非字符串键（int/float/bool/None 之外）以 `str()` 兜底后作键、键字符串化碰撞仍整体退化 `str(v)`（§10）；指令**位置违例**统一 P201（`:return` 函数外、`:function` 非顶层（含嵌套）、`:elif`/`:else` 错位等，§6/§11）；源文件解码失败 → L102（§4.1）；`--var` 拦截严于绑定目标规则（额外拦 `main`/`prompt`，动机见 DESIGN §6）；**终审末轮追加**：字符串常量发射侧**转义保真**——CPython 会规范化字面量内 `\r`（单/双引号内孤立 `\r` 直接 SyntaxError），pygen 对含 `\r`（及 tokenizer 可改写控制字符）的常量退化为非 raw 转义形式，兑现 §4.4「原样保留」（DESIGN §5.2/R21）；非提升位置 `import *` → C300（§9.2）；嵌入形态宿主会话未落盘时 `:save` → A501（§8，DESIGN §8.6）；`--` 分隔符对齐 argparse 语义、连接器同规则（DESIGN §9.1/§10）；`${}` 直接调用运行时函数属未承诺行为（§9.1）。**终审后补丁**：`:read` 冻结转出 JSON-safe **值**（容器结构保留、非字符串化文本，§7/§10）；注解赋值（如 `${X: int = 5}`）不提升、留在 `main`（§9.2）；**插值双形式**（翻转 E2「无 `$()` 之分」与 §4.2「`$(` 普通文本」两条既决）：`${}` 发起型（构造即冲刷点——纯语句先冲刷再执行、表达式独立 `emit(text(…))`，行号 1:1、保序）、`$()` 合并型（立即求值暂存 `__pcl_tN = text(…)`、纯语句不打断，织入当前段单条 emit、从不冲刷；求值副作用先于同段前置文本落 sink、不保序），两形式内容规则同构（§4.2/§10、DESIGN §5.2）；**裸糖 `$prompt`**——文本位置 `$` + 完整标识符 `prompt` ≡ `$(prompt)`（其余 `$name` 普通文本；构造内部不识别 `$`，`${$prompt}`/`$($prompt)` 拼写废除 → C310；文本转义改为 `$$` → 字面 `$`（取代原 `\${`，`\` 回归普通字符））。**终审冻结（last review）追加**：文件末尾孤立 `\r` 视作行终止符剥离（§4.4）；独行消除不触及跨行构造吞并的换行（§4.4）；`$$$prompt` 消解示例与单遍扫描表述（§4.3）；`yield` 不入 P203——`:function` 生成器语义按 Python、顶层 `yield` → C310（§7）；无 sessionFile 会话（正向 `--pi-arg --no-session`）的 `:save` → A501（DESIGN §8.3）。
