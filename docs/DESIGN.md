# PCL 实现设计（纯 Python 包 + pi 适配）

- 状态：v0.1，**终审通过**（[DSL.md](DSL.md) 与本文均已终审；终审修订已并入：§6 `run_program` 模块实例隔离、§8.1/§8.2 reply 兜底缓存每 pass 重置、§8.3 `:save` 命名次序与 embed 跳过重命名，R2/R14 随之更新；终审复核修订已并入：§5.1/§5.2/§6/§8.3/§9.1/§11——`:read` 快照预序列化冻结、sys.path 入口行为、`--var` 名校验、公共 API 签名、未落盘会话 token `load` 预检 → R430、R406 优先于 A504，R20 随之新增；终审末检修订已并入：§6/§8.6/§10/§11——`--var` 拦截表述澄清与 sys.path 不回滚备注、text() 键规则同步、embed 未落盘会话 `:save` 定码 A501、`--connector-path` 措辞、新增测试项（动态嵌套 pass / text() 键）；终审末轮修订已并入：§5.2/§9.1/§10/§11/§14——字符串常量发射侧 `\r` 转义保真（R21 随之新增）、非提升位置 `import *` → C300、`--` 分隔符 argparse 对齐、新增测试项（`\r` 保真 / `import *` / `--` 语义）；终审后补丁已并入 §5.2/§6/§9.1/§10/§11/§15——AnnAssign 不提升、reads 转出 JSON-safe 值措辞、`--var` 切分与 `reply` 有意放行、gen/check 退出码呈现、`text()` 深度备忘；**插值双形式定案**（`${}` 发起型：冲刷+独立 emit+保序；`$()` 合并型：立即求值暂存、织入单条 emit、不保序——DSL §2/§4.2/§7/§10、§5.2 发射模型与 §3/§11 随之更新；裸糖 `$prompt`：文本位置 ≡ `$(prompt)`、构造内 `$` 一律 C310、转义 `$$` → `$`）；**终审冻结（last review）修订已并入 §8.1/§8.3/§11**——无 sessionFile 会话的 `:save` 定码 A501（正向 `--pi-arg --no-session` 同 embed 守卫）、`--name` 启动命名备注、测试项补全（EOF `\r` / 跨行构造独行消除 / `yield` 放行））
- 架构决定：**宿主为纯 Python 包**；`.pcl → 生成 Python 源 → 同解释器执行`；语言为 v0.1（插值双形式 `${}`/`$()`（含跨行 raw 字符串）、pass 自动提交、`:function` 多参数、`:for/:while…:done` 统一终结、缩进无语义）
- 范围：总体架构、编译/代码生成、运行时、桥接层与 pi 适配（含上下文）、CLI、测试、打包与里程碑

---

## 1. 目标与约束

**功能目标**

1. 实现 DSL v0.1 模板层；脚本层直接复用宿主解释器（全生态，含 C 扩展）；
2. 拉起 pi 并经 IPC 驱动 agent：pass 提交、结构化写入、回复；上下文三指令映射 pi session；
3. 桥接层抽象，其他 agent 工具只增适配子包；
4. 反向形态：pcl-connector 在 pi 内注册与 CLI 对齐的 `/pcl` 命令族（run/gen/check/version，§9.1），`/pcl run` 在**当前 pi 会话**中执行 PCL 程序（嵌入模式，§8.5）。

**非功能约束**

- 形态：pip 包，入口命令 `pcl`；Python ≥3.10；**运行时零第三方依赖**（仅标准库）；
- 性能瓶颈在 agent 往返；模板编译为毫秒级；
- v1 平台 Linux / macOS。

---

## 2. 总体架构

```
+----------------------- pcl（纯 Python 包） -------------------------+
|  cli.py（run / gen / check）                                        |
|    │ ① 编译：tlex ─► tparse ─► pygen ─► 生成 .py（可读、pcl:行号）  │
|    │    （生成源落地 <cache>/<stem>-<sha8>.pcl.py，复用 .pyc）      │
|    │ ② 执行：importer 加载模块（加载层：:function/顶层 import/  │
|    │    字面量赋值）→ with Run: main(prompt)（traceback 指向缓  │
|    │    存文件、原生可读；import 永不运行模板体）                  │
|    │        ▲ 调用                                                  │
|    │        ▼                                                       │
|    │   pcl/runtime.py：emit / text / submit / save / load /         │
|    │      new_ctx / push_sink / pop_sink（当前 Run 的代理；Run     │
|    │      对象持有 sink 栈、bridge、中止标志）                  │
|    │        │ submit(prompt, reads, writes)  ▲ reply / writes      │
|    ▼        ▼                               │                      |
|  IAgentBridge（Null / Script / Pi）─────────┘                      |
+------│--------------------------------------------------------------+
       │ subprocess stdin/stdout JSONL（pi 内建 RPC 模式，不自建 socket）
       ▼
  pi --mode rpc -e <pcl-connector>
       │   pcl-connector 扩展（TS）：/pcl 命令族（机器子命令 pass 承载 pass 提交）、pcl_write/pcl_read 工具、
       │   before_agent_start 注入读写协议；/pcl 命令族反向驱动（§8.5/§9.1）
       ▼
     LLM（agent 循环至 agent_settled；上下文 = pi session，
          压缩交给 pi 自动 compaction）
```

**架构决策**

- A1（IPC 复用 pi RPC）、A2（pcl-connector 是语言契约的 pi 侧实现）、A6（不自研 VM，CPython ceval 即 VM）；
- **A10 纯 Python 宿主**：零嵌入/零 ABI 负担、原生 traceback、库形态可用，测试/调试/贡献门槛全部受益。
- **A11 生成源落地缓存**：`<缓存根>/pcl/<stem>-<sha8>.pcl.py`（缓存根 = `$XDG_CACHE_HOME`，未设则 `~/.cache`；`--cache DIR` 可覆盖、`none` 关闭，§5.3/§10）；经 importlib loader 加载缓存文件（traceback 直接指向该文件，且真正复用/生成 `.pyc`，见 §5.3）；模块 `__file__`/`__package__` 按源 `.pcl` 路径覆写（相对 import 按源目录解析）；sha 不匹配（源或编译器版本变化）则重生成。
- **A12 库形态一等公民**：`python -m pcl` 等价 CLI；`from pcl import compile_program, run_program` 供程序化使用；运行时状态收敛在 `Run` 对象中，可多 run 并存（SIGINT 处理仅在 CLI 形态注册）；**模板全局亦随 run 隔离**——`run_program` 每次加载全新模块实例（不进 `sys.modules`，§6），import hook 路径保留正常 Python 模块缓存语义（DSL §9.3）。
- **A13 双向驱动、单一协议**：正向 = pcl 拉起 `pi --mode rpc` 做对端；反向 = pi 内 `/pcl` 命令族（CLI 对齐）经连接器拉起 `pcl --agent embed`，连接器把**同一套** JSONL 命令/事件（§8.1–8.2；上下文切换的接续见 §8.5–8.6）代理到当前会话——协议零新增，仅端点两态（§8.5）。

---

## 3. 组件划分

| 组件 | 模块 | 职责 |
|---|---|---|
| 模板编译器 | `tlex.py` / `tparse.py` / `pygen.py` | `.pcl` 词法/解析/检查 → 生成 Python 源 + 行号映射 |
| import 互操作 | `importer.py` | `.pcl` 的 FileFinder/`import_module`/`import_from_path`（run 专用：每次加载新模块实例、不入 `sys.modules`，§6）；`.py` 优先序；`install_importer`（幂等，CLI 内建） |
| 运行时 | `runtime.py` | emit/text/submit/save/load/new_ctx/push_sink/pop_sink；Run 对象（sink 栈） |
| 桥接层 | `bridge.py` | `IAgentBridge`、Null、Script（测试桥） |
| pi 适配 | `pibridge.py` | PiBridge：pi 子进程 + JSONL RPC 客户端 + 上下文管理；embed 传输（§8.5：自身 stdio 为通道） |
| 上下文 | pibridge.py | token 生成/解析（无映射文件） |
| CLI | `cli.py` | run / gen / check / version |
| 连接器 | `pcl-connector/`（独立包，TS） | 白名单登记、pcl_write/pcl_read、协议注入；`/pcl` 命令族（CLI 对齐）+ embed 协议代理（§8.5/§9.1） |

---

## 4. 目录布局与打包

```
pcl/                       # 单仓两包：主包与 connector 拆包分开发布（§12）
├─ pclang/                 # Python 主包（PyPI 分发名 pclang）
│  ├─ pyproject.toml
│  ├─ src/pcl/
│  │  ├─ __init__.py     # 公共 API：compile_program / run_program / RunResult
│  │  ├─ tlex.py         # 模板词法：$$ 转义与 $prompt 裸糖、配平闭合（tokenize：括号深度 + 字符串/注释感知；${} 按 {}、$() 按 ()）、
│  │  │                  #  ASCII 行首/行尾空白剥除、独行消除（含仅语句插值行）、插值双形式 ${} 与 $()（文本位置裸糖 $prompt ≡ $(prompt)）、
│  │  │                  #  跨行构造识别（三引号字符串，含 `${r"""…"""}` 原始文本）
│  │  ├─ tparse.py       # AST（dataclass）+ 块配对 + 静态检查
│  │  ├─ pygen.py        # 发射器：AST → Python 源 + genLine→tplLine 表
│  │  ├─ runtime.py      # 运行时 API
│  │  ├─ importer.py     # .pcl import hook（install_importer / import_module；`pcl run` 内建）
│  │  ├─ bridge.py       # IAgentBridge / NullBridge / ScriptBridge
│  │  ├─ pibridge.py     # PiBridge：子进程、JSONL、上下文切换（token 生成/解析）
│  │  └─ cli.py          # argparse 入口
│  └─ tests/             # pytest（见 §11）
└─ pcl-connector/          # pi 扩展（独立分发，不在 Python wheel 内；安装方式见 §12）
   └─ index.ts             # 无构建：pi 经 jiti 直接加载 TS
```

```toml
# pyproject.toml（要点）
[project]
name = "pclang"                         # PyPI 分发名（`pcl` 已被占位包占用）；import 名/CLI 命令仍为 pcl
requires-python = ">=3.10"
dependencies = []                      # 运行时零依赖
[project.scripts]
pcl = "pcl.cli:main"
pclang = "pcl.cli:main"               # 别名：uvx/pipx 按可执行名匹配，使 `uvx pclang` 直接可用（§12）
```

开发依赖：pytest、ruff。

---

## 5. 编译与代码生成

### 5.1 AST

AST 节点（dataclass）：Text/Interp/If/While/For/Break/Continue/Function/Return/Save/Load/NewCtx（`:elif`/`:else` 为 If 节点的分支臂、非独立节点；注释词法期整行消除、不进 AST）——`Interp` 为插值节点（带形式字段 `${}`/`$()`；文本位置裸糖 `$prompt` 词法归一为 `$(prompt)`），持有原样简单语句列表；**Pass 为块节点**：`Pass{read, write, body: [NodeP]}`（read/write 各至多一个名字或 None；body 为 `${:pass}` 之后直至**下一个指令节点**（或 EOF）的全部输出构造，不含指令；发射器在 body 后、终止指令前插入提交序列）；`Function` 节点含原样 `params` 字段（缺省 `prompt=""`）。语句内容不做语义解析，原文转交 Python 做语法检查（C310 映射行号；`${}` 语句列表由发射器 ast 拆分，见 §5.2）。

### 5.2 发射规则（与 DSL §6/§7 一一对应）

- 文本 → `emit("…")` 常量；三引号 raw 字符串经插值路径同为常量（可含换行；两种定界符）；**字符串常量发射转义保真**：CPython tokenizer 在字符级规范化源码行结束符（`\r\n`/`\r` → `\n`）、不区分是否位于字符串字面量内——单/双引号内孤立 `\r` 直接 SyntaxError、三引号内 `\r` 静默变 `\n`——故 pygen 发射字符串常量前检测 `\r`（及任何会被 tokenizer 改写的控制字符），命中即退化为**非 raw 转义形式**（`\r` 以 `\\r` 转义发射；raw 语义靠转义保真，模板层无感知），DSL §4.4 的 `\r` 原样保留承诺由此兑现（R21）；**发射模型（append + emit，语义按定界符）**：pygen 维护单条待发射 `emit(a + b + c …)` 合并段——文本常量按源序追加；**`${}` 为发起型**：构造即冲刷点（先冲刷合并段，纯语句随后原样执行、每个表达式语句独立 `emit(text(<expr>))`，均行号 1:1；副作用发射与前后文本**保序**，且不与前后合并）；**`$()` 为合并型**：从不冲刷——表达式语句**立即求值**暂存 `__pcl_tN = text(<expr>)`（行号 1:1、源序）并追加暂存引用，纯语句原样立即执行、不打断合并段；指令构造（块边界、`:pass` 冻结与开闭/提交序列、reply 发射）与 EOF 亦为冲刷点（冲刷先于该构造生成的任何代码，含 `:if`/`:while`/`:for` 的条件/迭代式求值），合并不跨冲刷点/块边界；`$()` 的求值即源序（暂存即时），**唯一不保证**：求值期间的发射副作用（嵌套 pass 的 reply 等）会**先于同段未冲刷前置文本**落 sink——需保序用 `${}`（DSL §7/§10）；冲刷织成的合并 emit 仅含常量与暂存引用（不含用户代码求值）——两种形式的 C310/R400 均归因到各自构造行（独立 emit 行/暂存行，E8 精确），合并段尾注标行区间（如 `# pcl:5-7`）、映射表记录区间；
- 插值（`${}`/`$()`，DSL §10）→ 用 `ast.parse` 拆分**简单语句**列表（出现复合语句 → C300，两形式同规）：语句原样发射；**表达式语句**按形式分道——`${}` → 独立 `emit(text(<expr>))`（构造先冲刷；行号 1:1），`$()` → 立即求值暂存 `__pcl_tN = text(<expr>)`（行号 1:1、源序）并 append 进合并段（无条件插入，`None` → `null`；按源序）；插值不产生任何交互；**语句列表无表达式语句 → 该行为无输出构造、参与独行消除**（静态判定，复用本节 ast 拆分，两形式同规；统一规则：行内全部构造（指令/纯语句插值，可混排）无输出即整行消除，DSL §4.4）
- pass（DSL §7）→ `__pcl_reads = {"CTX": __pcl_freeze(CTX)}`（**先于 `push_sink()` 构建并即刻按 DSL §10 规则序列化冻结**——名字未定义此刻即 NameError=R400；body 内 `${}` 语句对该名的**重绑定或原地修改**均不影响快照，冻结值已 JSON-safe；`__pcl_freeze` 为运行时内部函数、随生成头按需导入，`__pcl_` 前缀已保留、不新增用户可见保留名）+ `push_sink()` + body（纯输出构造）照常发射（一切 emit 进 prompt 缓冲）+ **在终止指令（或 EOF）前**插入 `__pcl_buf = pop_sink()` + `__pcl_r = submit(__pcl_buf, reads=__pcl_reads, writes=(…))`（无 `:read`/`:write` 时对应实参省略，§6；信令层三键恒出现，§8.2） + `reply = __pcl_r.reply` + 逐名条件写回 + `emit(reply + ("\n" if __pcl_buf.endswith("\n") else ""))`（**reply 尾换行折叠 = 运行期判定**：提交缓冲 trim 前以 `\n` 结尾即补一个换行——pass 体末为插值时同样正确，DSL §7；prompt trim 后为空 → submit 跳过桥接、返回空结果，DSL §7），随后照常发射终止指令；**静态检查**：pass 体不得为空（P202）、pass 体内插值构造（`${}`/`$()`）语句不得为 break/continue/return（P203——原样 Python 会跳过提交点；用本节 ast 拆分即可检查）；发射器断言每个 push_sink 有同层配对 pop_sink；
- 控制流/函数 → 直接映射 Python 缩进块；块边界 = 指令对（`:fi`；`:done` 统一终结 `:for`/`:while`；`:endfunction`），缩进只存在于生成源（tlex 先剥除行首/行尾 ASCII 空白，DSL §4.4——源码缩进无语义、仅为可读性；`${:function NAME(P)}` 的 `(P)` 原样进 `def NAME(P):`，缺省 `(prompt="")`）；**空块体**（`:if`/`:while`/`:for`/`:function` 体为空、空模板的 `main`）→ 发射 `pass` 填充；
- `${:save/:load/:new}` → `名字 = save()` / `load(名字)` / `new_ctx()`（名字为单个 Python 变量名，实参非名字 → P200；`save` 返回当前会话 token、`load` 取变量值为 token 切换；`save` 目标计入 DSL §9.2 的 global 并集）；
- **模块布局（两相，DSL §9.2）**：顶层发射 `:function` 定义 + 顶层插值构造（`${}`/`$()`）中**整体为 import / 字面量赋值**的语句列表（`ast` 判定：语句列表中**每条语句**均为 import 或字面量赋值，二者可混排；字面量赋值 = RHS 为 `Constant`、纯 `Constant` 容器，或数值 `Constant` 的一元 `+`/`-`/`~`——`X = -5` 提升、`X = 1+2` 不提升、注解赋值（AnnAssign）不提升（仅普通 `=` 赋值参与提升）；绑定目标为简单名、`as` 别名或元组解包均可；**`import *` 仅限可提升语句列表**——Python 禁止函数内 `import *`、`*` 绑定名不可静态枚举而无法入 global 并集，不提升的插值构造（`${}`/`$()`；混排其他语句、或位于 `:if` 块/`:function` 体内等非顶层处）含 `import *` → C300（复用本节 ast 拆分判定，DSL §9.2））；其余模板体收进 `def main(__pcl_prompt=""):`——函数首先**恒发射序言** `global prompt` + `prompt = __pcl_prompt`（入口实参经内部形参接收、就地提升为模块全局：`prompt` 即普通模块全局名、可被模板绑定；形参直接命名 `prompt` 会与 `global prompt` 语法冲突（Python: name is parameter and global），故经内部名中转；`prompt` 不参与下述并集，`--var` 注入它亦被拒，§6；发射形态可与其余 global 声明合并，DSL §3/§9.2），随后（源序）发射模板体，并对 `reply`、**main 内（`:function` 体外、任意嵌套深度）pass 的 `:write` 名**与 main 内一切**绑定目标**——赋值（含增强赋值与 walrus `:=`——含推导式内 NamedExpr：PEP 572 使其绑定包含作用域，绑定目标分析需覆盖）、`:for` 变量、`:save` 目标、`import` 绑定名、`del` 目标（含嵌套控制流；对已提升到加载层的名字声明与否等价，超集无害）——的并集发射 `global` 声明（DSL §9.2）；`main` 无返回值约定——输出单通道经 Run（§6）；`main`/`__pcl_`/8 个运行时名为保留名（DSL §9.2；`:function main` → C300）；`:function` 名 `prompt`/`reply` 同为保留（→ C300——序言/顶层 pass 写回会覆写模块级同名 `def`；作为普通绑定目标不保留，DSL §9.2）；
- 生成头部**按需导入**该模块生成代码实际用到的运行时名（如 DSL §3 示例仅 `emit, submit, text, push_sink, pop_sink`；含 `:read` 的模块另导入内部 `__pcl_freeze`，见上）；这 8 个运行时名为保留名（DSL §9.2；**一律保留，与是否按需导入无关**）——用户侧任何绑定目标与之同名 → C300，杜绝 `${save = …}` 之类毒化生成调用。

### 5.3 缓存与行号

- 生成源写 `<缓存根>/pcl/<stem>-<sha8>.pcl.py`（缓存根 = `$XDG_CACHE_HOME`，未设则 `~/.cache`；`--cache DIR` 覆盖，§10）；sha = hash(源文件, 编译器版本)；命中则直接复用；**落盘原子性**：经同目录临时文件 + `os.replace` 原子替换（并发首编同一源，不致第三方 import 到半截 `.pcl.py`）；**陈旧条目 GC**：同 stem 仅保留最近 2 个 sha、更旧的随写随删（防缓存无限增长，容忍分支间来回切换）；
- **缓存加载走 importlib**（`spec_from_file_location` + `SourceFileLoader`），而非裸 `exec(compile(...))`——只有经 loader 才真正复用/生成 `.pyc`；编译文件名 = 缓存路径（traceback 指向 `.pcl.py`，原生可读）；
- 模块 `__file__`/`__package__`/`__path__` 按**源 `.pcl` 位置**设置（加载后覆写 loader 默认值）——**相对 import 按源目录解析**；`__pcl_source__` 经 exec globals 注入而非内嵌生成源文本（同内容异路径不撞同一缓存文件）；
- 每个源自模板的行带 `# pcl:N` 尾注（人读）；错误报告用内存映射表回译（traceback 本身已指向 `.pcl.py`，回译仅用于"模板行号"标注）。
- **`--cache none`**：生成源不落盘、不生成 `.pyc`——`compile()` 的 filename 用虚拟名 `<stem>.pcl.py`（traceback 帧指向该名、行号为生成源行号，模板行号回译标注同常，§10）；

### 5.4 `pcl check`

模板编译 + `compile(src)` 语法检查（不执行、不起 agent）。

---

## 6. 运行时（runtime.py）

**API（生成代码视角）**

| 函数/对象 | 签名 | 说明 |
|---|---|---|
| `emit` | `(s: str) -> None` | 追加当前 sink（pass 体内 = prompt 缓冲；跨函数调用共享，宏语义） |
| `push_sink` / `pop_sink` | `() -> None` / `() -> str` | （内部）压入/弹出输出缓冲栈；`:pass`…自动提交的隔离机制，用户代码不应直接调用 |
| `text` | `(v) -> str` | DSL §10 字符串化（dict/list/tuple → 紧凑 JSON，容器内不可 JSON 化值与 NaN/Infinity 以 `str()` 兜底、非字符串键（int/float/bool/None 之外）同以 `str()` 兜底后作键，键碰撞或整体失败退化为 `str(v)`；bool → true/false；None → null；float → repr；其余 str()） |
| `submit` | `(prompt: str, reads: dict[str, Any], writes: tuple[str, …]) -> PassResult` | 提交前对 prompt 做 **ASCII 空白双端 trim**（空格/`\t`/`\n`/`\r`/`\f`/`\v`；全角空白不剥——全角-only prompt 不判空，DSL §7）后提交桥接层（**空 prompt 跳过**：不调桥接、返回空 `PassResult`，DSL §7）；`reads` 为生成代码在 pass 开始**预序列化冻结**的 JSON-safe 快照字典（单条目——`:read` 只认一个名字，DSL §7；冻结按 `text()` 转换规则在 pass 开始一次完成（转出 JSON-safe 值而非文本，DSL §7/§10），`NaN`/`Infinity` 含顶层一律 `str()` 兜底为 JSON 字符串值，保证发往连接器的 JSON 严格合法），随 `/pcl pass` 信令下发（与提交文本一体，§8.2）；`writes` 为单名元组（`reads`/`writes` 缺省 `{}`/`()`，无 `:read`/`:write` 时生成代码省略）；阻塞至 agent 空闲；越权写入抛 `PclError(R406)`——**先于空回复判定**（越权与 A504 并存时 R406 优先）；JSON→Python 深度上限 32（超限 R400） |
| `save` / `load` / `new_ctx` | `save() -> str` / `load(token: str) -> None` / `() -> None` | 上下文（§8.3）：`save` 返回当前会话 token（生成代码赋给 `:save` 的变量）；`load` 切换到 token 对应会话；token 未知/失效 → R430，非 str → R431 |
| `PassResult` | `.reply: str`、`.writes: dict[str, Any]` | |

**执行环境（示意）**

```python
def run_program(path, prompt="", *, agent="pi", ..., var_overrides=None):
    sys.path.insert(0, realpath(dirname(path)))     # 入口 .pcl 所在目录插 sys.path[0]（幂等，对齐 python script.py；
                                                     #  ${import helpers} 由此解析同目录库，DSL §9.3；插入不回滚——
                                                     #  库形态长进程多次 run 不同目录会在 sys.path 累积条目，v0.1 已知且可接受）
    mod = importer.import_from_path(path)            # 每次加载全新模块实例：唯一模块名、独立命名空间、不入 sys.modules
                                                     # （模块实例隔离见下；缓存与 .pyc 复用不受影响，§5.3）
                                                     # → 执行加载层（§5.2 模块布局）
    for k, v in (var_overrides or {}).items():      # --var：加载层之后、main 之前注入模块全局
        setattr(mod, k, v)                           # （覆盖加载层同名字面量赋值）
    with Run(bridge=make_bridge(agent, ...), out=OutputSink(...)) as run:
        mod.main(prompt)                             # 模板体；输出经 emit 单通道流入 run；main 无返回值
    return run.result()                              # RunResult：输出文档 + 终态（traceback 指向 .pcl.py）
```

- **模块实例隔离（终审修订）**：`import_from_path` 每次**加载全新模块实例**（唯一模块名、独立命名空间、不注册 `sys.modules`）——同进程多次/并发 `run_program` 互不共享模板全局与 `--var` 注入；`install_importer` hook（Python→DSL，DSL §9.3）保留正常 `sys.modules` 模块缓存语义——**隔离仅覆盖入口模块**：`${import helpers}` 等传递导入经 hook 走 `sys.modules` 正常缓存，并发 run 间共享被导入 `.pcl` 的模块全局（Python 语义）；缓存文件与 `.pyc` 复用不受影响（§5.3）；
- **`--var` 保留名拦截**：注入名命中 `main`/`__pcl_`/8 个运行时名或 `prompt` → 启动即拒绝（按 C300 语义报告），防止运行期毒化生成调用。**该拦截严于 DSL §9.2 的绑定目标规则**（`main` 在该规则下仅作为 `:function` 名保留、作为普通绑定目标不保留）：`--var` 额外拦 `main`/`prompt` 的动机是注入时点在加载层之后、`main()` 调用之前——覆写入口函数/序言目标会直接破坏本次运行（`prompt` 由 main 序言独占，输入走形参，§5.2）；NAME 须为合法 Python 标识符，否则用法错（退出码 1，§10）；注入**非保留**的 `:function` 名不被拦截（模块级 `def` 被覆盖、调用处 TypeError → R400，后果自负）；注入 `reply` 亦不被拦截——非结构性名，注入值存活至首个 pass 写回（有意放行，与绑定目标不保留规则一致）；
- **runtime 代理**：生成头 `from pcl.runtime import emit, …` 拿到的是**当前 Run 的代理**（contextvar；无当前 Run 时调用任何运行时函数 → `PclError(R405)`，DSL §11）；CLI/库形态均在 `with Run(...)` 中调用 `main`（多 run 并存互不干扰，A12/R11）；Run 对象持有 sink 栈、bridge、中止标志；`Run(agent=…)` 为 `Run(bridge=make_bridge(…))` 的便捷构造（DSL §9.3 示例用前者）；
- **SIGINT**（仅 CLI 形态）：handler → `run.abort()` → `bridge.abort()` → `PclError(R409)`，退出码 130；
- **线程模型**：主线程执行生成代码；PiBridge 读线程只解析 JSONL 入队；`submit()` 在阻塞等待期间泵队列，把 `message_update` 增量转发 `--trace`（stderr）。
- **公共 API（M3 冻结）**：`compile_program(path) -> str`（编译返回生成源文本，不执行；缓存照常，§5.3）；`run_program` 如上；`RunResult{output: str, module: ModuleType}`——`output` 为输出文档全文，`module` 为本次运行的新模块实例（可读模板全局终态，如 DSL §12.1 的 `SCORE`/`HISTORY`/`cx`）。

---

## 7. bridge.py（Null / Script）

| 桥 | 行为 |
|---|---|
| NullBridge | `--agent null`：reply = prompt 原文，writes 为空（纯模板调试）；上下文指令为 no-op，token 合成自增 |
| ScriptBridge | `--agent script --script f.jsonl`：按序回放 `{reply, writes}`，writes 为任意 JSON；确定性 e2e 测试；上下文 token 合成自增（save/load 可回放）；**回放耗尽**（提交次数超过脚本条数）→ 立即抛 A510（消息含已消费/总条数），不静默复用末条；空 prompt 跳过（DSL §7）不调桥、不消耗回放条目 |

---

## 8. pibridge.py 与上下文

### 8.1 子进程与协议

- `subprocess.Popen(["pi", "--mode", "rpc", "--name", f"pcl-{pid}-{ts}", *connector_args, *pi_args], stdin/stdout=PIPE, stderr=PIPE)`（启动名仅供 /resume 辨识从未 `:save` 的运行；`:save` 时按 §8.3 重命名——两套命名有意并存）；`pi_args` 由 `--pi-arg`（可多次）收集、原样透传 pi 命令行（如 `--pi-arg "--model …"`）；connector 路径 `--connector-path`（**缺省 `none`** = 用预装扩展；也可直指 connector 的 `index.ts` 源文件——主包不内置 connector，安装方式见 §12）；
- **分帧**：自维护 buffer，仅按 `\n` 切分并剥离尾部 `\r`（pi rpc.md 要求：JSON 字符串内合法含 U+2028/U+2029，禁用通用行分割语义）；
- 就绪探测：spawn 后发 `get_state` 等首个成功响应，再以 `get_commands` 验证 `/pcl` 已注册（连接器缺失/未加载 → A500 快速失败，报错附安装指引：预装到 pi 扩展目录或 `--connector-path` 直指源文件，见 §12）；`pcl` 条目多于一条或带数字后缀（同名扩展被双重装载——如预装与 `--connector-path` 并存时 pi 注册 `/pcl:1`/`/pcl:2`，信令分发目标不确定）→ 同样 A500，报错附去重指引；
- 读线程分派：`response`（按 id 关联请求）、`tool_execution_start`（pcl_write 写入，`args` 为任意 JSON——rpc.md 已确证）、`message_update`（trace 流式）、`message_end` / `turn_end`（**缓存末条 assistant text**——`get_last_assistant_text` 为空时的兜底；**每 pass 重置**：`/pcl pass` 提交时清零，兜底不跨 pass 携带旧文本，§8.2）、`agent_settled`（pass 边界）、`extension_error`（**在途 pass 时 → A501 快速失败**：`command:pcl` = 连接器 handler 异常——response 仍 ok、不可依赖，§8.2）/ `extension_ui_request`（记录/忽略）。

### 8.2 pass 时序

```
pcl(PiBridge)                           pi(RPC)
  │ /pcl pass {"writable":[…],"reads":{…},"text":…}
  │──prompt──────────────────────────────────►│  连接器登记白名单/快照（模块状态），
  │                                            │  await pi.sendUserMessage(text)
  │                                            │  （缺省不展开）→ LLM（注入 pcl_write 协议）
  │◄─tool_execution_start(pcl_write args)─────│  writes（任意 JSON）
  │◄─message_update…（--trace 流式）───────────│
  │◄─agent_settled─────────────────────────────│
  │◄─response ok（严格晚于 settled）───────────│
  │──get_last_assistant_text─────────────────►│
  │◄─reply─────────────────────────────────────│
```

**每 pass 唯一信令 `/pcl pass {…}`**（登记 + 文本一体）：PiBridge 发一条 `prompt`，消息体 = `/pcl pass ` + 紧凑 JSON（`ensure_ascii=False`，单行——`text` 内换行经 JSON 转义；payload **三键恒出现**，无 `:read`/`:write` 时 `writable`/`reads` 为 `[]`/`{}`——“submit 实参省略”仅为生成代码层面（§6），连接器对省略键与空集等价容忍）；连接器 handler 登记白名单/快照后 `await pi.sendUserMessage(text)`（缺省 `expandPromptTemplates:false`）——pass 文本**永不裸发**。

状态机 `idle → pass-sent → settled → fetched-reply`（settled 可能**先于** response 到达——见下；事件泵按序缓存，response 仅作屏障）；超时（`--timeout`，默认 300s；**按次计**——每次 `submit` 等待 agent 空闲的独立时限，非整 run 总预算）→ 发 `abort` → A502；子进程退出 → A503；JSON 解析失败 → A501。

时序已按 rpc.md 与 pi 源码确证（pi@0.85.1，M2 冒烟复核）：

- RPC `prompt` 的 response 经 `preflightResult` 回调发出（rpc-mode.js）：普通文本在轮次启动前即 ok；扩展命令路径则**严格晚于 handler 完成**——而 `sendUserMessage` = `prompt(expandPromptTemplates:false)` 且 **await 完整轮次**（`agent_settled` 在其 finally 发出）→ **response ok 严格晚于 `agent_settled`**（pcl 侧事件先到、响应后至，状态机须容忍此序；RPC 命令循环不被占住——`void session.prompt(…)`，`abort` 等命令可并发处理）；
- handler 抛错（payload 非法 / 无模型 / 鉴权失败 / compaction 进行中）被 `_tryExecuteExtensionCommand` 捕获 → `extension_error(command:pcl)` 事件 + **response 仍 ok**——pcl 须监听 `extension_error` 判败（→ A501，§8.1），两种形态同规则；
- 扩展**命令 ctx 无 `sendUserMessage`**（仅 ReplacedSessionContext 有）→ 连接器用**模块级 `pi.sendUserMessage`**（随会话替换重绑，与 §8.6 F4 一致）；
- 扩展命令不经 LLM、不写入会话——信令无上下文污染；**`/` 开头 pass 文本免疫**：信令（命令分发面）与文本（JSON 值）结构性分离，pi 对 prompt 的 input expansion（扩展命令分发、skill/模板展开，`expandPromptTemplates` 缺省 true）不再构成碰撞面；embed 代理同样不再按 `/pcl` 前缀区分信令与文本（此前以 `/pcl `/`/skill:` 开头的 pass 文本会被误路由，§8.5）。

reply 提取以 `get_last_assistant_text` 为主、事件缓存兜底（§8.1）；**兜底缓存每 pass 重置**——`/pcl pass` 提交即清零（agent 末轮仅 `pcl_write` 无文本时，兜底不会取到上一 pass 的旧回复；仍为空 → A504，宁空错不错值）。

### 8.3 上下文 = pi session

| PCL | PiBridge 行为 | pi RPC |
|---|---|---|
| 启动 | 当前上下文 = 本次运行初始 session（embed：宿主当前会话，§8.5） | 启动即有 |
| pass | 追加当前 session（默认行为，无额外操作） | —— |
| `:new` | 新建匿名上下文并切换（响应 `data.cancelled == true` → A501；connector 不注册 `session_before_switch`，理论不触发；embed：经模块级桥接接续，§8.6） | `new_session` |
| `:save x` | 生成代码 `x = save()`：提交未决 pass 后，取当前 session 的 **token** 返回——token = `get_state` 的 **`sessionFile` 绝对路径**（`switch_session` 唯一直接消费的形态；`sessionId` 无对应消费命令，不用） | **正向**：`get_state`（仅为命名取 basename）→ `set_session_name("pcl:" + basename 去扩展名)`（人工 /resume 辨识；token 为绝对路径、目录前缀对全体会话相同，故取 basename）→ **重取 `get_state`、以末次 `sessionFile` 为 token**（终审修订：改名若轮转会话文件，token 仍指向现路径；是否真会轮转列 M2 冒烟，R14）。**embed**：跳过 `set_session_name`（不重命名宿主用户会话），单次 `get_state` 即得 token |
| `:load x` | 生成代码 `load(x)`：取变量值为 token 直接切换；**切换前预检 token 文件存在性**（本地 stat）——不存在（典型：目标会话从未收到 assistant 回复、pi 惰性落盘未写文件，见下）→ R430（把 pi 侧 `SessionManager.open` 对缺失文件"按空会话兜底"的静默错值转为显式报错）；失败/文件缺失（`success:false`）→ R430，`data.cancelled` → A501；embed：经模块级桥接接续（§8.6，预检同样在 pcl 侧先行） | `switch_session(sessionPath)` |

- token 的生成/解析在 PiBridge 内完成（= `sessionFile` 路径，`switch_session` 直接消费），**无映射文件**；跨运行持久化归用户（普通 Python 读写自己的文件，DSL §8 配方）；
- **无 sessionFile 的会话**（正向 `--pi-arg "--no-session"`，或 embed 形态宿主会话未落盘，§8.6）：`get_state` 无 sessionFile → `:save` 判 **A501**（无可用 token，宁报错不返回空值——与 §8.6 embed 守卫同一化）；
- **惰性落盘（R20）**：pi 的 session 文件在**首个 assistant 回复后**才写盘（`SessionManager._persist` 无 assistant 不 flush；`newSession` 仅预分配路径；`SessionManager.open` 对缺失文件按空会话兜底——pi@0.85.1 源码已核）。`:save` 早于任何 pass 时 token 指向尚不存在的文件：同 run 内 `:new`/`:load` 往返或跨运行 `:load` 均被上述预检拦为 R430（宁报错不错值）；文档声明：需要可靠续聊的会话应在 save 前至少完成一次 pass；
- 切换只影响后续 pass；被扩展事件取消等边缘情形 → A501 上抛；
- **压缩**：pi 自动 compaction 兜底，PCL 不干预。匿名上下文（`:new`）与历史 session 由 pi 侧管理，PCL 不做清理（运维备忘）。

### 8.4 生命周期
退出/异常：关 stdin → 等待进程结束（超时 SIGTERM → SIGKILL 兜底）；stderr 尾部并入 A500/A503 诊断。

### 8.5 嵌入模式（`--agent embed`，由 pi 内 `/pcl run` 驱动）

**协议端点反转、报文不变**：正常模式 pcl 拉起 `pi --mode rpc` 为对端；嵌入模式由连接器拉起 `pcl run <file.pcl> [PROMPT] --agent embed …`（`pcl` 经 PATH 解析，环境变量 `PCL_BIN` 可覆盖），PiBridge 以**自身 stdin/stdout 为 RPC 通道**（stdout 让给协议、不再打输出文档）；帧规则（§8.1）、pass 时序（§8.2）、错误码全部复用，零新增协议；上下文映射（§8.3）完整复用——`:save` 经 `get_state` 合成、`:new`/`:load` 经模块级桥接接续（§8.6）。连接器侧为**协议代理**（命令 handler 内执行——会话控制方法仅命令上下文可用，恰得其所）：

| pcl → 连接器（JSONL 命令） | 连接器动作（当前会话） |
|---|---|
| `prompt` `/pcl pass {…}` | 登记白名单/reads + 经模块级 `pi.sendUserMessage(text)` 入当前会话（缺省不展开——`/` 开头文本原样入会话；`await` 完整轮次后回 response ok，§8.2） |
| `get_state` | 合成 `{sessionFile: ctx.sessionManager.getSessionFile(), …}`（PiBridge 只消费 sessionFile，§8.3） |
| `get_commands` | 合成（列出连接器已注册命令——含 `/pcl`；§8.1 就绪探测复用） |
| `set_session_name` | **embed 下 PiBridge 不发送**（`:save` 不重命名宿主会话，§8.3；映射保留兼容：若发来则 `pi.setSessionName(name)`，模块级 API、经共享 runtime 重绑至当前会话） |
| `new_session` / `switch_session` | 经当前绑定执行（须 L2——接管/降级规则见 §8.6；`:load` 跨 cwd 预检 → A522、L1 降级 → A523、旧版连接器 → A520） |
| `get_last_assistant_text` | 连接器缓存的末条 assistant text（`message_end`/`turn_end` 事件） |
| `abort` | `ctx.abort()` |
| 未知命令 | 回 `success:false`（pcl 侧 → A501，即 R16 版本深移护栏） |

- **事件转发**：`tool_execution_start`（pcl_write 写回）、`message_update`（--trace）、`message_end`/`turn_end`（reply 兜底）、`agent_settled`（pass 边界）序列化后写入 pcl stdin；`extension_error` 为 RPC 层事件、扩展不可订阅——不由 pi 转发，而由代理在自身 handler 抛错时**合成**（见下"失败可见性"）；`extension_ui_request` 记录/忽略、不转发；
- **上下文三指令的支持面**：三指令均支持——`:save` ✓（`get_state` 合成，无会话替换）；`:new`/`:load` 在 pi 侧是*会话替换*（`ctx.newSession`/`ctx.switchSession`）：替换会拆毁代理所在的扩展实例（旧运行时 teardown、事件订阅与命令上下文作废——extensions.md「Session replacement lifecycle」），协议通道不能依赖实例状态续转——桥接状态上移**扩展模块级**，替换后由新实例接管（设计见 §8.6；失败码 A520–A523：旧版连接器拒绝/孤儿/跨 cwd/降级绑定）；
- **stdout 独占**：协议帧独占子进程 stdout——embed 模式下 pcl 运行时把模板/用户 Python 的 `sys.stdout` 重定向至 stderr（`${print(…)}` 等不致污染 JSONL 流；污染帧 → 对端解析失败 → A501）；
- **输出与退出码**：embed 强制 `-o`（连接器生成临时文件；用户显式 `-o` 透传）；pcl 退出后连接器按退出码（§10）读取输出文件呈现（TUI：setWidget/notify；stderr 尾部并入诊断）；
- **前置与并发**：handler 先 `await ctx.waitForIdle()` 再 spawn；运行中经 setStatus 提示。运行期间用户的其他输入照常进入同一会话（当前上下文语义），pass 回复归属以「pass 提交后首个 agent_settled」为界——混入轮次可能错位 reply 归属，v0.1 已知限制（R15），后续可加会话独占；用户 Esc 中止 agent 轮次时 `agent_settled` 照常发出（pcl 按（可能为空的）回复继续，空则 A504 兜底；pcl 子进程不随 Esc 终止）；pass 提交瞬间恰逢用户轮次流式中 → `pi.sendUserMessage` 抛错（缺 `deliverAs`）→ A501（R15 的失败化形态——宁报错不错位）；
- **失败可见性**：命令 handler 抛错时 pi 的 prompt response 仍为 ok、错误经 `extension_error` 事件流出（pi 既定行为，源码已核 §8.2）。**嵌入形态模拟同一行为**：代理自身 handler（`/pcl pass` 提交、上下文操作等）抛错时仍回 response ok、并合成 `extension_error(command:pcl)` 事件写入 pcl stdin——PiBridge 两种形态判败零分叉（A13）；`command:pcl` 为 handler 异常；无模型/鉴权失败等提交期错误同路流出 → A501。

### 8.6 嵌入模式的上下文接续（`:new`/`:load` 与会话跟随）

**定位**：嵌入形态的 `:new`/`:load` 涉及 pi 的*会话替换*，替换会拆毁代理所在的扩展实例（§8.5）——接续不能依赖实例状态；本节为 v0.1 的接续设计，**协议零新增命令**，仅失败语义细化。关键结论：unix-socket 重连在主路径上**不必要**——子进程管道的属主是 pi 进程而非扩展实例，会话替换不碰 fd；真正的要点是把桥接状态从"扩展实例"上移到"扩展模块"。

**可行性事实（pi@0.85.1 源码/docs 已核；M4 实现前复核）**

| # | 事实 | 出处 |
|---|---|---|
| F1 | **扩展模块级状态跨会话替换存活**：扩展按 (cwd, 代数) 缓存*工厂函数*；同 cwd 的替换（`:new` 必然；同项目 `:load`/用户切换亦然）复用同一模块实例，仅重新执行工厂（新 Extension 对象、共享模块作用域）。缓存清理仅两处：cwd 变化、`ctx.reload()` | extensions/loader.js（`extensionCache`/`useExtensionCacheCwd`/`loadExtensionModule`）；agent-session.js `reload()` → `resourceLoader.reload()` → `clearExtensionCache()` |
| F2 | **替换时序**：`before_switch` → teardown（旧实例 `session_shutdown` → dispose）→ createRuntime（新实例 `session_start`）→ [`newSession` 专有 `setup`，**晚于**新实例 `session_start`——不能用于向新实例投递发现信息] → `withSession`（旧闭包 + ReplacedSessionContext） | agent-session-runtime.js（`teardownCurrent`/`createRuntime` 调用序/`finishSessionReplacement`） |
| F3 | **ReplacedSessionContext 可作接管后的主绑定**：= 新会话命令上下文的属性快照 + 绑定新会话的 `sendUserMessage`/`sendMessage`；其 `newSession`/`switchSession` 经 `assertActive()` 绑定新会话 runner，存活至下一次替换——可链式 `:new`→`:load` | agent-session.js `createReplacedSessionContext`；extensions/runner.js `createCommandContext` |
| F4 | `pi.sendUserMessage` 是模块级 API，不要求命令上下文（空闲即触发轮次；流式中需 `deliverAs`）——pass 文本提交可脱离命令 handler | extensions.md `pi.sendUserMessage` |
| F5 | **管道随进程存活**：pcl 子进程 stdin/stdout 管道属主为 pi 进程，会话替换只拆扩展运行时、不关 fd——只要 ChildProcess/流对象仍被引用（模块级持有），协议通道不断 | Node child_process 语义 + F1 |
| F6 | teardown 先 `session.abort()`（在席轮次的 `agent_settled` 照常发出，旧实例 handler 仍活）再 shutdown/dispose——pass 在途时被切换，settled 仍可达 pcl（与 Esc 语义一致，空回复 → A504 兜底） | agent-session-runtime.js `teardownCurrent`；§8.5 Esc 条目 |
| F7 | 事件只分发到当前会话的实例 handler（旧 runner dispose 后不再投递）；替换窗口内新会话空闲——无重复转发、无丢失，泵无需会话门控 | extensions/runner.js `emit`/`invalidate` |

**设计总则**

1. **桥接上移模块级**：`moduleBridge`（单例）持有子进程、流、在途命令表、reply 缓存与当前*绑定*；扩展实例退化为"注册点 + 事件泵"——工厂每次执行都注册同一组 handler，handler 只做 `moduleBridge?.onEvent(e)`；
2. **绑定 = 会话能力束**，两级：**L2 完整**（命令 ctx / ReplacedSessionContext：`sendUserMessage`、`abort`、`sessionManager`、会话控制 `newSession`/`switchSession`/`waitForIdle`）；**L1 受限**（事件 ctx + `latestPi`：前三者有、会话控制无，见 auto-follow）。任何 `/pcl` 子命令执行时以该命令 ctx 把绑定升级回 L2（用户敲任一 `/pcl` 命令即恢复完整能力）；
3. **单活动桥**：同一 pi 进程同时只允许一个嵌入 run（第二个 `/pcl run` → notify 拒绝，指引等待或正向 CLI）——事件归属唯一化，会话跟随才有确定语义（放宽多桥列开放问题）；
4. **串行规则**（成文既有隐式约定）：pcl 侧上下文操作严格等待响应后才发下一命令；连接器侧命令泵单队列顺序处理。

**连接器模块结构（pcl-connector/index.ts）**

```ts
let moduleBridge: Bridge | null = null;      // 单活动桥（F1：跨替换存活）
let latestPi: ExtensionAPI | null = null;    // 工厂每次执行刷新

class Bridge {
  proc; stdin; stdout;                       // F5：模块持有，替换不断
  state: "active" | "switching" | "awaitingAdoption" | "broken";
  binding: { ctx; level: 1 | 2 };             // §8.5 代理表的执行体
  pending = new Map<id, cmd>();
  replyCache = "";                            // 末条 assistant text（事件泵喂，§8.5；每 pass 重置：/pcl pass 提交清零，§8.2）
  async serve();                              // 唯一命令泵：读行→分派→binding 执行→写响应（写全部 EPIPE 安全）
  adopt(ctxLike, level);                      // session_start / withSession / /pcl 命令时调用
  detach(reason); dispose(kill?);
}

export default (pi) => {
  latestPi = pi;
  // F7：无需会话门控——只有当前会话的实例会收到事件
  for (const ev of ["agent_settled", "tool_execution_start", "message_update", "message_end", "turn_end"])
    pi.on(ev, (e) => moduleBridge?.onEvent(e));
  pi.on("session_start",  adoptionRule);       // 见下
  pi.on("session_shutdown", shutdownRule);     // 见下
  pi.registerCommand("pcl", …);                // §9.1；run 子命令：waitForIdle → new Bridge(…, binding = 该命令 ctx, L2)
                                              // → moduleBridge = b → await b.done → 呈现（经 b.binding，不碰捕获 ctx）
}
```

**三条接管规则**

| 触发 | 规则 |
|---|---|
| `session_shutdown` | reason=`quit` → `dispose`（**先关 stdin**——pcl 读线程 EOF → 既有 A503 语义；宽限后 SIGTERM 兜底，免信号先于 EOF 击杀）；reason=`reload` → 模块即将重载（F1 例外）→ 尽力 notify"reload 将中断 /pcl run"，标记 `broken`（走孤儿路径）；reason∈{new, resume, fork} 且**非桥发起**（无 `switching` 标记）→ `awaitingAdoption`（不杀进程、不停泵） |
| `session_start` | `moduleBridge` 处于 `awaitingAdoption` 且子进程活着 → `adopt(事件 ctx, L1)`（setStatus"pcl 嵌入运行已随会话切换接续"）。同 cwd 必走到这里（F1）；跨 cwd 时本模块已被重载、`moduleBridge` 为 null → 无人接管 → 孤儿路径 |
| `/pcl` 任一子命令 | handler 以当前命令 ctx `adopt(ctx, L2)`（能力恢复入口；含 `/pcl version`） |

**序列：`:new`（`:load` 同型）**

```
pcl                       连接器（命令泵，旧闭包）                  pi 会话层
  │ new_session ────────────►│ binding 须 L2（L1 → reason embed-no-session-control → pcl A523）
  │                          │ state = switching
  │                          │ await binding.ctx.newSession({        │ before_switch（他扩展可 cancel）
  │                          │   withSession: (ctx2) =>              │ teardown：abort 在席轮次（settled 经旧泵转发，F6）
  │                          │     binding = {ctx2, L2}              │   → shutdown → dispose（旧实例 handler 拆除）
  │                          │ })                                    │ createRuntime：新实例 session_start（switching ≠ 待接管，不误 adopt）
  │ ◄─ {"id":N,"success":true} ─┤（newSession 返回后写；            │ withSession（旧闭包，ReplacedSessionContext）
  │                          │  cancelled → success:false + data.cancelled → pcl A501）
  │ get_state ──────────────►│ 新 sessionFile（后续 :save 取新 token）
```

- `:load x` 预检：token == 当前 sessionFile → 直接 ok（no-op，免一次无谓替换）；`SessionManager.open(token).getCwd() != 当前 cwd` → `reason:"embed-cross-cwd"` → pcl **A522**（模块必重载、桥必孤儿，明确引导走正向 CLI；`open/getCwd` 仅见于源码、公开 extensions.md 未载——M4 复核项，见 R17）；打开失败 → 既有 `success:false` → R430；
- 链式切换（`:new` 后再 `:load`）：绑定已是 ReplacedSessionContext（L2，F3），直接再调 `switchSession`，无需用户介入。

**序列：用户切换会话（auto-follow）**

用户在嵌入 run 进行中 `/new`、`/resume`、`/fork`（TUI 自发，无 withSession）→ 旧实例 `session_shutdown`（非桥发起）→ `awaitingAdoption` → **同 cwd**：新实例 `session_start` → `adopt(事件 ctx, L1)`：事件照转、pass 经 `latestPi.sendUserMessage` 入新会话（F4）、`get_state`/`abort` 可用；**会话控制降级**——后续程序 `:new`/`:load` → `reason:"embed-no-session-control"` → pcl **A523**（提示：执行任一 `/pcl` 命令恢复，或改用正向 CLI）。**跨 cwd（或 reload）**：模块重载、无人 adopt → 泵内 adoption 时限（常量 10s）到期 → 在途命令回 `reason:"embed-orphaned"` → pcl **A521**；随后**先关 stdin**（无在途命令、正执行 Python 的 pcl 经 EOF 以 **A503** 呈现——孤儿路径失败码取决于此刻 pcl 是否阻塞在命令响应上）→ 宽限后 SIGTERM 兜底；结果呈现经 `binding` 尽力而为（stale 抛错则 console.error + 输出文件尾注说明）。

**失败语义（协议增量：零新命令，仅失败 reason 成文）**

失败响应统一为 `{"id":N,"success":false,"data":{"reason":…,"cancelled"?:true}}`，pcl 侧映射：

| reason | pcl 错误 | 场景 |
|---|---|---|
| `embed-ctx-unsupported` | A520 | 旧版连接器（未实现接续的版本）拒绝——版本深移护栏（R16），v0.1 连接器自身不发出 |
| `embed-orphaned` | A521 | adoption 时限内无新实例认领（跨 cwd 用户切换 / reload / 防御路径）；仅当 pcl 有在途命令——空闲中的 pcl 经 stdin EOF 以 A503 呈现（见 auto-follow） |
| `embed-cross-cwd` | A522 | `:load` 目标 cwd ≠ 当前（预检拒绝，免跑进孤儿路径） |
| `embed-no-session-control` | A523 | auto-follow 后的 L1 绑定收到上下文操作 |
| （无 reason，`cancelled:true`） | A501 | 既有：`session_before_switch` 被他扩展取消 |
| （无 reason） | R430 | 既有：`:load` 目标打开失败 |

上下文操作适用 `--timeout`（按次，同 §8.2）；超时 → `abort` → A502。子进程死亡/管道 EOF → 既有 A503 生命周期（§8.4）。

**边界情形**

| 情形 | 行为 |
|---|---|
| pass 在途时用户切换 | teardown 先 abort：settled（可能空回复 → A504）经旧泵转发，随后 auto-follow；与 Esc 语义一致（F6） |
| 起始会话未持久化（无 sessionFile） | `:new` 走 inMemory 分支可用，但 `get_state` 合成 sessionFile=undefined → 后续 `:save` 由 PiBridge 判为 **A501**（协议错误：无可用 token，宁报错不返回 undefined——终审末检定码）；文档声明：嵌入 run 前让宿主会话落盘（首条消息后即持久化） |
| 连续多次 `:new`/`:load` | 绑定逐次刷新为最新 ReplacedSessionContext（F3 链式），旧 ctx 自然作废 |
| 第二个 `/pcl run`（活动桥存在） | notify 拒绝（单活动桥），指引正向 CLI |
| pcl 被 kill -9 | 泵写响应 EPIPE → `dispose()` 清理 |
| 他扩展在 `session_before_switch` 弹确认 | 用户交互期间 pcl 阻塞于命令响应——`--timeout` 兜底 |
| 用户在接续窗口（10s 内）切回原会话 | 同 cwd → 照常 adopt，无需特判 |

**pcl 侧（pibridge.py，仅 embed 分支）**：`new_ctx()`/`load()` 在 embed 下照常发 `new_session`/`switch_session`（与正向同码路径）；响应分派按上表把 reason → A52x。其余零改动（§8.5 代理表中该两命令的行为 = "经当前绑定执行"）。

**测试（M4）**：单测（伪 JSONL 对端驱动连接器：切换链、reason 映射、EPIPE、adoption 时限）；冒烟（真 pi）：embed `:new` → 后续 pass 落新会话；`:save`→`:load`（同 cwd）往返；`:load` 跨 cwd → A522；用户 `/new` 中途 → auto-follow 接续 + 后续 `:new` → A523 → 用户执行 `/pcl version` 后恢复 L2；用户跨 cwd `/resume` 中途 → 在途命令 A521（10s 内）/ 空闲时 A503（stdin EOF）；reload 中途 → 同左；pass 在途切换 → A504/继续；第二 `/pcl run` 被拒；`quit` → pcl EOF → A503（宽限后 SIGTERM）。

**后续加固备忘（消除孤儿路径）**：embed 启动即另备 unix socket（`$TMPDIR/pcl-embed-<pid>/bridge.sock`，0600；stdio 管道仍为主通道）；切换前连接器把交接记录（socket 路径、pid、epoch、目标会话）写入用户级磁盘文件（或 `pi.appendEntry` 随会话文件走——原备忘的持久化思路在此保留）；被重载的新模块在 `session_start` 扫记录 → 连 socket → 握手 `{"role":"connector-resume","epoch":…}` → pcl 传输层切到 socket、弃管道。覆盖跨 cwd `:load`、reload、乃至 pi 重启后开同一会话续跑（需 pcl 侧孤儿宽限配合）。届时 A521/A522 退化为 socket 也不可用的兜底。

**开放问题**：auto-follow 是否提供关闭开关（如连接器配置 `embedFollow=false` → 用户切换即按 A521 处理）；adoption 时限（10s）是否独立于 `--timeout`（`--ctx-timeout`）；单活动桥是否放宽为"按会话绑定多桥"（事件按桥归属过滤，R15 语义需重定义）。

---

## 9. pcl-connector（TS）

### 9.1 命令面（对 pi 宿主暴露：单命令 /pcl，含机器子命令 pass）

- **`/pcl`：连接器唯一注册的命令——人类命令面板/补全只出现它**（与 CLI 对齐的用户入口；pi 命令名不含空格——`/pcl run f.pcl P` 中 `run` 起为 args，由 handler 分派；`getArgumentCompletions` 提供 run/gen/check/version 子命令补全——机器子命令 `pass` 刻意不进补全）：
  - `/pcl run <file.pcl> [PROMPT…] [选项…]`：嵌入当前会话运行——`waitForIdle` → spawn `pcl run … --agent embed -o <tmp>` 并代理协议（§8.5），结束后呈现输出与退出码；PROMPT = file 之后、首个 `--` 开头 token 之前的全部 token 以空格连接，字面 `--` 分隔符对齐 argparse 语义——其后的 token 一并按序并入 PROMPT（`--` 只移除自身；与 CLI 一致，§10）；正向专属选项（`--agent/--pi-bin/--connector-path/--pi-arg/--script`）被拒——连接器侧解析即拒（notify 提示、不 spawn；用法错语义，与 CLI 用法错同归退出码 1，§10）；
  - `/pcl gen <file.pcl>` / `/pcl check <file.pcl>`：纯编译直通（无 agent 交互），spawn 后捕获 stdout；退出码 0 → stdout 呈现，非 0（如编译错）→ stdout、stderr 尾部与退出码一并呈现（与 `/pcl run` 呈现规则一致，§8.5）；
  - `/pcl version`：版本直通；连接器可借此与 pcl 主包做协议握手（R16）；
  - 未知/缺省子命令 → 用法提示（不列 `pass`——机器通道不在用法中宣传）；
- **`/pcl pass {…}`：机器子命令，每 pass 唯一信令（登记 + 提交文本一体，§8.2）**——折叠为 `/pcl` 子命令而非独立命令（`pi.registerCommand` 无 hidden 选项，独立注册必然进人类命令面板）；payload = `{"writable":[…],"reads":{…},"text":…}`（args = `pass` 之后的**原样余串**、紧凑单行 JSON，不按空白拆分——值内空白/换行无损；`writable` 单名、`reads` 单条目——值已是生成代码在 pass 开始冻结的 JSON-safe 值（§5.2），PiBridge 直接 `ensure_ascii=False` 序列化）；handler：登记 → `await pi.sendUserMessage(text)`（缺省不展开——`/` 开头文本免疫，§8.2）；正向/嵌入两种形态同套信令——嵌入由连接器本地消化（§8.5）；`pass` 随 v0.1 协议面一体冻结（R16）；人类误敲无害（缺 `text`/非法 JSON → handler 抛错仅出 `extension_error`，不触发 agent 轮次）。

`/pcl` 命令骨架（示意）：

```ts
pi.registerCommand("pcl", {
  description: "PCL：/pcl run <file.pcl> [PROMPT] — 在当前会话执行 PCL（与 pcl CLI 对齐）",
  getArgumentCompletions: (prefix) => {
    const subs = ["run", "gen", "check", "version"]
      .map((s) => ({ value: s, label: s }))
      .filter((i) => i.value.startsWith(prefix));
    return subs.length ? subs : null;
  },
  handler: async (args, ctx) => {
    const [sub, ...rest] = args.trim().split(/\s+/);
    if (sub === "pass") return submitPass(args.trim().slice(4).trim()); // 机器子命令：登记 + pi.sendUserMessage（§8.2/§9.2）
    if (sub === "run") return runEmbedded(ctx, rest);   // §8.5：waitForIdle → spawn pcl --agent embed → 代理
    if (sub === "gen" || sub === "check" || sub === "version")
      return passthrough(ctx, [sub, ...rest]);           // 纯编译直通，无 agent 交互
    return usage(ctx);                                    // 用法提示
  },
});
```

### 9.2 工具与注入

- `pcl_write`（参数 = 名→任意 JSON 值的对象，typebox `Type.Record(Type.String(), Type.Unknown())`）：写回通道；扩展侧先行拒绝非 writable 名单的写入并引导模型当轮重试；写入值随 `tool_execution_start` 事件回流主机；
- `pcl_read`（可选 `names: string[]`）：读取通道；**连接器本地应答**（查 `/pcl pass` 快照，不经主机往返——pass 期间程序阻塞在 submit，无法应答）；`names` 缺省 = 全部可读；名单外名字返回错误文本并列出可读名单；
- `before_agent_start`：注入 pcl_write/pcl_read 使用协议（仅当 read/write 名字存在时提及，减少无关指令）。

`pcl_read` 工具示意：

```ts
pi.registerTool({
  name: "pcl_read",
  label: "PCL read",
  description: "读取当前 pcl pass 可读的 PCL 变量。",
  parameters: Type.Object({
    names: Type.Optional(Type.Array(Type.String(), { description: "变量名列表；缺省=全部可读" })),
  }),
  async execute(_id, params) {
    const snap = current?.reads ?? {};
    const want = params.names ?? Object.keys(snap);
    const bad = want.filter((n) => !(n in snap));
    if (bad.length)
      return { content: [{ type: "text", text:
        `错误：${bad.join(", ")} 不可读；可读：${Object.keys(snap).join(", ") || "（无）"}` }], details: {} };
    const out = Object.fromEntries(want.map((n) => [n, snap[n]]));
    return { content: [{ type: "text", text: JSON.stringify(out) }], details: {} };
  },
});
```

---

## 10. CLI

```
pcl run <file.pcl> [PROMPT…] [选项]      # 多个位置 token 以空格连接绑定 prompt（--prompt 同义，冲突以位置参数为准；`--` 分隔符遵循 argparse 语义——其后 token 视作位置参数并入 PROMPT、`--` 自身移除，连接器侧同规则 §9.1）
pcl gen  <file.pcl>                     # 打印生成的 Python 源
pcl check <file.pcl>                    # 模板编译 + 生成源 compile() 检查（不执行）
pcl version

--prompt TEXT      --var NAME=VALUE（注入模块全局；解析序：VALUE 先 `ast.literal_eval`，成功即注入该值、失败按原串注入 str——`N=5`→int 5、`S=hello`→"hello"、`S='5'`→"5"；NAME=VALUE 按**首个 `=`** 切分（VALUE 可含 `=`）、同名多次以末次为准；时点与保留名拦截见 §6）
--agent pi|null|script|embed（embed = 嵌入模式：自身 stdio 为 RPC 通道、强制 -o；由 pi 内 /pcl run 拉起，用户一般不直接指定）   --script PATH   --pi-bin PATH
--connector-path PATH|none（缺省 none = 用预装扩展——是「用预装」而非「禁用」，无可用连接器即 A500，见 §12）   --pi-arg ARG（可多次，原样透传 pi 命令行）
--timeout SEC(300；按次计，见 §8.2)   -o FILE（只写文件，不再打 stdout）   --trace   --cache DIR|none
```

退出码：`0` 成功；`1` 编译期（L/P/C）与**用法错**（argparse 默认 2 一律覆写为 1——用法错属"未开始执行"，与编译期同类，避免与运行期 2 冲突）；`2` 运行期（R）；`3` 桥接（A）；`130` SIGINT（见 DSL §11）。输出统一 UTF-8 编码——写 stdout；给定 `-o` 时**只写文件**（不重复打 stdout）。

---

## 11. 测试策略（pytest）

| 层 | 内容 |
|---|---|
| 单元 | 模板词法（`$$` 转义（`$${`/`$$prompt`/`$$$$`；`\$` 无转义、原样输出）、裸糖 `$prompt`（`$promptX` 不触发）、**配平闭合**（`${}` 按 `{}`、`$()` 按 `()`）：嵌套 `{}`/`()`、字符串/三引号/f-string 内闭合符、`${len(A)}`、`${ {"a":1} }`、`${D={"k":1}}`、`#` 注释吞闭合符→L100、注释未独行→C305；ASCII 空白剥除（全角空格保留；CRLF 行尾 `\r` 随行剥离、输出换行统一 `\n`、文件末尾孤立 `\r` 同剥离）；独行消除（仅语句插值行（`${}`/`$()`）、指令与纯语句插值混排行、跨行无输出构造起始行（换行由构造吞并、不得重复移除））；跨行三引号 raw 字符串（构造跨行识别/未闭合→L100/含 `"""` 时换 `'''`/两引号序列都含时拆段/内容 `${`、`\` 原样）、`\r` 转义保真（CRLF 源 + 跨行 raw 字符串输出逐字节含 `\r`；文本行中间孤立 `\r` 原样进入输出——发射侧非 raw 转义，§5.2/R21））、插值双形式解析（复合语句拒绝→C300 两形式同规；非提升位置 `import *` → C300——顶层单行合法、混排/`:if` 内/`:function` 体内拒绝，§5.2）、表达式语句无条件插入（`None` → `null`）与 `_ =` 丢弃惯用法、`${}` 独立 emit/冲刷保序与 `$()` 立即求值暂存（`__pcl_tN`）/合并段织入（含求值副作用先于同段前置文本落 sink 的不保序声明项）、块配对（`fi`/`done`）、**空块体合成 `pass`**、pass 自动提交边界（指令终止/EOF 终止/空体/`${}` 控制语句拒绝→P203、`yield` 放行（`:function` 变生成器语义声明，DSL §7））、`:function` 参数列表透传、运行时保留名作为绑定目标 → C300（赋值/形参/`:for`/`:save`/`:write`/`:function` 名/import as/del）、`:function main/prompt/reply` → C300（序言/pass 写回复写同名 `def` 的护栏；`prompt`/`reply` 作为普通绑定目标仍合法）、发射器黄金输出（固定 `.pcl` → 生成源快照；含 reads 快照先于 push_sink、main prompt 序言、发射模型（`${}` 独立 emit+冲刷、`$()` 立即求值暂存+合并段单条拼接、不跨冲刷点/块边界）的断言）、`prompt` 绑定不入 global 并集、`${}` 空语句 no-op |
| runtime | text() 字符串化（含不可 JSON 化/NaN/循环引用兜底、非字符串键 `str()` 兜底作键与键碰撞整体退化，DSL §10）、动态嵌套 pass（pass 体内 `${}` 调用含 pass 的函数：sink 栈隔离、内层 reply 落外层 prompt 缓冲、内层 `:write` 写函数局部，DSL §7）、submit 的 reads 快照传递（**body 内 `${}` 语句改动不影响快照**——重绑定与原地修改均然，pass 开始预序列化冻结，§5.2）与写回语义（Script 桥记录断言）、空 prompt 跳过（空 PassResult）、ASCII 双端 trim（全角-only prompt 不判空、照常提交）、无 Run 上下文调用 → R405、深度上限、上下文 API（save 返回 token、load 切换；stale token→R430） |
| e2e-script | DSL §12 完整示例逐字节断言（输出 + 退出码）；pass 体末为插值时 reply 尾换行折叠（运行期判定）；Script 桥回放耗尽 → A510（确定性失败）；`${}` 语句位置嵌套 pass 的 reply 与前后文本保序（DSL §12 草稿落点；`$()` 不保序为声明行为） |
| smoke-pi（marker，需 API key） | 单 pass 标量写入、结构化写入（list/object）、write-only pass（末轮仅 `pcl_write` 无文本）→ A504 且兜底缓存不跨 pass 泄漏（§8.2）、pcl_read 按需拉取（含不可读名拒绝）、上下文三指令（new/save/load 后续 pass 命中正确 session；save → 改名/compaction → load 仍命中，R14/§8.3；save 早于首个 pass → `:new`/`:load` 往返 → R430（惰性落盘预检，R20/§8.3））、连接器缺失→A500（`get_commands` 验证）；嵌入冒烟：pi 会话内 `/pcl run` 完成 pass/写回/`:save`（§8.5，含 gen/check 直通、正向选项被拒、stdout 独占、`--` 分隔符 PROMPT 语义与 CLI 一致（§9.1/§10）、运行中用户输入的已知限制声明）；M4：嵌入 `:new`/`:load`/auto-follow/孤儿路径（§8.6 测试清单）；信令面：`/` 开头 pass 文本直通（两种形态）、`extension_error(command:pcl)` → A501（handler 注错；正向 = 真事件、嵌入 = 代理合成事件，§8.5）、response 晚于 `agent_settled` 的次序断言 |
| 库形态 | `from pcl import run_program` 冒烟（无 CLI） |
| import | hook：Python→DSL（`import t as a`、`from t import f as g`）、DSL→DSL（`${import t}`）、`.py` 优先、加载层提升判据（字面量/import，含 `X = -5` 提升、`X = 1+2` 不提升、注解赋值不提升）、main 的 `global` 语义（含 `:if` 内 `${import os}`、`${del X}`、walrus `:=` 目标（含推导式内 NamedExpr）均落模块全局）、包内相对 import（`pkg/__init__.py` + `pkg/tpl.pcl` 内 `from . import x`——`__package__` 按源目录覆写，§5.3/DSL §9.3）、`run_program` 多次调用模板全局隔离（每次新实例，§6）、被导入模块编译错 → ImportError |
| 模糊 | 模板词法/解析（M3+，hypothesis 或自写 fuzzer） |

---

## 12. 打包与部署

- **拆包**：主包与 connector 分开发布、互不依赖——Python wheel **不内置** `pcl-connector`（目录布局按此拆分，§4）；
- `pipx install pclang` / `uvx pclang` 即用（**分发名 `pclang`**——`pcl` 已被 PyPI 占位包占用；import 名与 CLI 命令仍为 `pcl`：`pip install pclang` → `import pcl` / `pcl run`；uvx/pipx 按**可执行名**匹配，`pclang` 别名脚本（§4）使 `uvx pclang` 直接可用，否则需 `uvx --from pclang pcl`）；也可在项目内作库使用；
- CI 矩阵：Python 3.10–3.14 × Linux/macOS；
- `pcl-connector`（本仓 `pcl-connector/`）无构建——pi 经 jiti 直接加载 TS；安装二选一：① 复制/链接到 pi 扩展目录（预装，`--connector-path` 缺省 `none` 即用），② `--connector-path` 直指 `index.ts` 源文件。缺失/未注册 → A500（报错附上述两条出路）；
- 连接器仅 `/pcl` 命令族需要宿主侧存在 `pcl` 可执行（PATH 解析，`PCL_BIN` 覆盖）；仅做 pass 交互（正向形态）时无此依赖。

---

## 13. 里程碑

M0–M4 全部属 v0.1 范围（含 §8.6 嵌入上下文接续）；无后续版本分层。

| 里程碑 | 内容 | 验收 |
|---|---|---|
| M0 | tlex/tparse/pygen + `pcl gen/check` + 黄金快照 | DSL §3 生成源与文档一致 |
| M1 | runtime + Null/ScriptBridge + e2e-script + importer（.pcl 模块化） | DSL §12 示例全绿；import 矩阵（含 as）通过 |
| M2 | PiBridge + connector + 上下文三指令 + smoke | smoke-pi 通过 |
| M3 | 嵌入模式：连接器 `/pcl` 命令族 + PiBridge embed 传输 + 冒烟；打磨：trace、超时/中断、缓存策略、库 API 冻结、模糊测试 | pi 会话内 `/pcl run` 跑通无上下文切换示例（如 DSL §3）＋ `:save` 冒烟；文档齐备 |
| M4 | 嵌入上下文接续（§8.6）：连接器 Bridge/接管规则、pcl reason→A52x 映射、auto-follow | §8.6 测试清单全绿（含跨 cwd/reload 孤儿路径）；pi 升级版本时回归 F1–F7 |

M2 前原定协议 spike 已**按 rpc.md 与 pi 源码落定**（§8.1–8.3）：①扩展命令 response 严格晚于 handler 完成（`/pcl pass` 经 sendUserMessage await 完整轮次——response 严格晚于 `agent_settled`）、命令文本不进 LLM 上下文、handler 异常经 `extension_error` 流出且 response 仍 ok；②`tool_execution_start.args` 为任意 JSON；③切换取消 = 显式 `data.cancelled` 字段、token = `get_state` 的 `sessionFile` 绝对路径；④reply 以 `get_last_assistant_text` 为主、事件缓存兜底。M2 冒烟照常复核。§8.6 的 F1–F7 同样已按 pi@0.85.1 源码核验，M4 实现前及 pi 升级时复核。

---

## 14. 风险与开放问题

> 编号含历史空洞（R4–R7 为评审中已关闭删除的项）；正文多处交叉引用 R15–R19，为免连锁改动保留原编号不重排。

| # | 风险 | 缓解 |
|---|---|---|
| R1 | 扩展命令经 RPC `prompt` 的响应时序假设 | **已确证**（rpc.md + pi@0.85.1 源码）：response 经 `preflightResult` 发出，扩展命令路径严格晚于 handler 完成（`/pcl pass` 经 `sendUserMessage` await 完整轮次 → 严格晚于 `agent_settled`，状态机容忍事件先到）；命令文本不进 LLM 上下文；handler 异常 → `extension_error(command:pcl)` 且 response 仍 ok（pcl 监听判败）；M2 冒烟复核 |
| R2 | 最后动作为工具调用时 `get_last_assistant_text` 为空；兜底缓存若跨 pass 残留会回放旧回复（静默错值） | PiBridge 缓存 `message_end`/`turn_end` 末条 assistant text 作兜底（零额外往返；**缓存每 pass 重置**——`/pcl pass` 提交清零，终审修订 §8.1/§8.2）；仍为空 → A504 |
| R3 | `switch_session`/`new_session` 可被扩展事件取消 | **已确证**：取消为显式 `data.cancelled` 字段；connector 不注册 `session_before_switch`；`:load` 失败→R430、`:new` cancelled→A501 |
| R8 | Python 异常即运行时语义（NameError→R400 等映射） | DSL §11 已声明；traceback 指向 `.pcl.py` + 行号回译 |
| R9 | 子进程生命周期：管道缓冲、僵尸、pi 非零退出、stderr 采集 | 读线程持续排空；退出路径统一 close→wait→terminate→kill |
| R10 | Python 版本行为差异 | CI 矩阵 3.10–3.14 |
| R11 | 库形态并发多 run | 状态全在 Run 对象；signal handler 仅 CLI 注册 |
| R12 | 生成源缓存与编译器版本漂移 | sha 含编译器版本号；不匹配即重生成 |
| R13 | sink 栈泄漏（`${}` 内控制语句跳过提交点） | 自动提交使指令无法跳过 pop_sink；pass 体内 `${}` 控制语句静态禁止（P203）+ 发射器断言 push/pop 配对 + e2e 回归 |
| R14 | pi compaction **或 `set_session_name` 改名**可能轮转 `sessionFile` 路径 → 已保存 token 失效（`load` → R430） | `:save` 已按「改名后重取 `sessionFile`」取 token（终审修订，§8.3）；M2 冒烟验证（save → 改名/触发 compaction → load）；若 compaction 仍会轮转，token 改取稳定会话标识或在文档声明该局限 |
| R15 | 嵌入模式运行期间用户输入混入同一会话 → pass 回复归属错位 | v0.1 声明已知限制（§8.5）；setStatus 提示运行中；提交瞬间恰逢用户轮次流式 → `sendUserMessage` 抛错 → A501（失败化而非错位）；后续可加会话独占（input 拦截） |
| R16 | 连接器与 pcl 主包版本漂移 → embed JSONL 协议不兼容 | 协议面冻结为 §8.1 命令/事件集合；连接器对未知命令回 `success:false`（pcl → A501）；`/pcl version` 握手 |
| R17 | 嵌入模式 `:new`/`:load` 需会话替换 → 拆毁代理所在扩展运行时 | **已设计接续（§8.6）**：桥接上移模块级（F1–F7 按 pi@0.85.1 核验）；残余：模块缓存行为属实现细节、`:load` 预检所用 `SessionManager.open()/getCwd()` 公开文档未载——M4 首项复核、pi 升级时回归；跨 cwd/reload 仍孤儿（A521/A522 兜底；socket 备胎消除，§8.6 加固备忘） |
| R18 | auto-follow 后绑定降级 L1 → 程序 `:new`/`:load` → A523 | 文案引导恢复（任一 `/pcl` 命令）或改用正向 CLI；开关 embedFollow 列开放问题 |
| R19 | 单活动桥约束限制并发嵌入 run | v0.1 声明（§8.6）；多桥放宽列开放问题 |
| R20 | pi 会话文件惰性落盘（首个 assistant 回复后才写盘；`SessionManager.open` 对缺失文件按空会话兜底）→ 未落盘 token 的 `:load` 静默丢上下文（pi@0.85.1 源码已核） | PiBridge `:load` 前预检文件存在性 → R430（§8.3）；文档声明 save 前至少完成一次 pass；M2 冒烟（save→`:new`→`:load` 往返 + 跨运行 load） |
| R21 | 生成源字符串字面量内 `\r` 被 CPython tokenizer 规范化（`\r\n`/`\r` → `\n`；单/双引号内孤立 `\r` → SyntaxError）→ DSL §4.4 `\r` 原样保留承诺失效/生成源 C310（3.14 已实测） | pygen 发射含 `\r`（及 tokenizer 可改写控制字符）的字符串常量一律退化为非 raw 转义形式（§5.2）；单元测试覆盖 CRLF 源跨行 raw 与孤立 `\r`（§11） |

---

## 15. 未来方向（备忘）

并行/多 agent、其他 agent 工具适配子包、REPL、生成源 `.pyc` 之外的增量缓存、读写值体积上限（`pcl_write` 写回 / `:read` 快照，v0.1 不设）、`text()` 输出侧递归深度上限（写入方向 JSON→Python 已限 32；病态深结构暂靠 RecursionError → R400 兜底）。
