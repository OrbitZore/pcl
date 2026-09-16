# PCL 设置文件方案（用户级 / 项目级）

- 状态：**已实现（v0.2.0.dev0）**——`pcl/settings.py` + CLI 接线 + `pcl config` + `settings.schema.json`；评审修订一轮（见文末「评审记录」）。schemastore.org 提交待发布时进行
- 范围：设置文件的发现/合并/校验规则、v0.1 配置项清单、潜在配置项全集、明确不配置的项
- 原则来源：DSL §1/§8（零自研库、无隐藏状态）、DESIGN §1（零第三方依赖）、§5.3（XDG 缓存）、§6/A12（库形态显式参数）、§8.6/§15（开放问题与未来方向）

---

## 1. 目标与原则

1. **只服务 CLI 层**：设置文件是 `pcl` 命令的默认值来源；**库形态（`run_program`/`compile_program`/importer）完全不读设置**——调用方显式传参（A12 多 run 并存的隔离不变式不受影响）。
2. **显式优先**：命令行显式参数 > 项目级 > 用户级 > 内置默认；配置只填默认，不改语义。
3. **零第三方依赖**：格式取 **JSONC 子集**（stdlib 可解析：预剥离字符串字面量之外的 `//` 行注释、`/* */` 块注释与尾随逗号——tsconfig/VS Code 先例；剥离器须正确跳过字符串内内容，URL 中的 `//` 不受影响）。TOML 因 3.10 无 `tomllib`（引入 `tomli` 违反零依赖）落选；纯 JSON 无注释是长期被诟病的 UX 缺陷，故取 JSONC。`"$comment"` 键约定保留兼容。
4. **单一事实源**：模型/provider 等已由 pi 自身设置管理的项不进 pcl 设置（透传经 `pi.args`）；语言语义（trim 集合、reply 折叠、`text()` 规则）一律不可配。
5. **无隐藏状态**：`--var`、prompt、上下文 token 等每次运行的值不进设置（与"token 交用户保管"哲学一致，DSL §8）。

## 2. 文件位置与发现

| 层 | 路径 | 说明 |
|---|---|---|
| 用户级 | `$PCL_CONFIG_FILE`（重定向，单文件）；缺省 `$XDG_CONFIG_HOME/pcl/settings.json`，未设 XDG 时 `~/.config/pcl/settings.json` | 与缓存 `$XDG_CACHE_HOME/pcl`（DESIGN §5.3）对称；文件不存在则跳过该层 |
| 项目级 | 自**入口 `.pcl` 文件所在目录**向上（含祖先目录）找到的**最近一个** `.pcl/settings.json` | 只取最近一个、不合并多层（git 风格，可预测）；`.pcl/` 是目录，与 `*.pcl` 模板文件无冲突 |

发现算法（伪码）：

```text
resolve_settings(entry) -> dict:
    files = [env PCL_CONFIG_FILE 或 XDG 配置文件]          # 用户级（可能缺失）
    for d in entry.parent 及其全部祖先目录:
        if d/".pcl"/"settings.json" 存在:
            files.append(该文件); break                     # 项目级（最近者胜）
    return 内置默认 ← 逐层浅合并(files)
```

- **基准目录**：`pcl run/gen/check` 以**目标 `.pcl` 路径**为入口（与 §9.3 的 `sys.path[0]` 模块解析基准一致——模板自包含、可移植）；嵌入形态 `/pcl run` 拉起的 `pcl` 子进程按同一规则发现，项目级设置自动生效。
- **相对路径解析**：设置内的相对路径（`cache.dir`、`pi.bin`、`pi.connector_path`、`script.path`）相对于**设置文件所在目录**解析（用户级同理），保证项目设置可移植。
- v1 平台 Linux/macOS；Windows 预留 `%APPDATA%\pcl\settings.json`（未来）。

## 3. 优先级与合并

**低 → 高**：内置默认 → 用户级 → 项目级 → 命令行显式参数。

- 标量键：高层覆盖低层。
- 节（`cache`/`pi`/`script`）：**节内浅合并**（未给的键保留低层值）。
- 数组特例 `pi.args`：**拼接**（用户级在前 → 项目级追加 → CLI `--pi-arg` 项再追加）——与 `--pi-arg` 可重复的追加语义一致。
- 环境变量不进入逐键优先级链：仅 `PCL_CONFIG_FILE`（重定向用户级文件）、`PCL_NO_PROJECT_CONFIG`（密封运行）与既有 `PCL_BIN`（连接器 spawn pcl 用，见 §5 嵌入节）。**有意不做逐键 env**（如 `PCL_AGENT`/`PCL_TIMEOUT`）：与设置文件重复、命名面膨胀（docker 式全量 env 等价物的代价）；机器级差异交由 `PCL_CONFIG_FILE` 指向的环境专属文件表达（12-factor 诉求由此覆盖）。若未来需要，插入位为 CLI > env > 项目级 > 用户级。

## 3.5 键分级与信任模型（项目级配置的供应链防线）

项目级 `.pcl/settings.json` 是**随仓库分发的不可信输入**（clone 即得）。若允许其在项目级配置执行面键，等于静默代码执行/资源重定向（npm/pip 生态的经典攻击面；pi 自身对项目资源亦有 `project_trust` 机制）。因此**键按级别分级**：

| 级别 | 允许的键 | 说明 |
|---|---|---|
| 项目级允许（安全集） | `agent`、`timeout`、`trace`、`cache.disable`、`cache.keep_per_stem`、`cache.dir`（相对路径，且解析结果须落在该设置文件目录之内） | 只影响本工具的行为参数与项目内写入 |
| **仅用户级**（执行面/外部资源） | `pi.bin`、`pi.connector_path`、`pi.args`、`script.path` | 任意可执行/任意扩展加载/任意命令行透传/任意回放文件 |

- 项目级文件出现"仅用户级"键：**报错 exit 1**（宁报错；类比 git 对可疑仓库的 `safe.directory` 处置），消息指明键名与迁移建议。
- 项目级 `cache.dir` 为绝对路径或逃逸出项目目录：报错 exit 1。
- 未来若需要"项目内共享模型绑定"等执行面配置：引入 pi 式**项目信任（trust-on-first-use）**机制后放开（见开放问题）。

## 4. v0.1 配置项清单（提案 schema）

```jsonc
// 完整形状（所有键可省略；"$comment" 约定为注释位）
{
  "$comment": "可选注释",
  "agent": "pi",                    // 默认 agent：pi | null | script | embed
  "timeout": 300.0,                 // pass 等待空闲的按次超时（秒，DESIGN §8.2）
  "trace": false,                   // 默认开 --trace（message_update → stderr）
  "cache": {
    "dir": null,                    // 生成源缓存目录；null = $XDG_CACHE_HOME/pcl（§5.3）
    "disable": false,               // true 等价 --cache none（不落盘/无 .pyc）
    "keep_per_stem": 2              // 同 stem 保留的缓存条目数（GC，§5.3）
  },
  "pi": {
    "bin": "pi",                    // pi 可执行（--pi-bin）
    "connector_path": "none",       // "none" = 用预装扩展；或直指 index.ts（§12）
    "args": []                      // 透传 pi 命令行（--pi-arg 累积）
  },
  "script": {
    "path": null                    // script 桥默认回放文件（--script；null = 必须显式给）
  }
}
```

随特性首发 **`settings.schema.json`**（JSON Schema，随 wheel 分发于 `pcl/` 包内并提交 [schemastore.org](https://www.schemastore.org)）：设置文件可用 `"$schema"` 键引用，编辑器即得补全与校验；未知键检测亦以 schema 为权威依据。`$` 前缀键（`$schema`/`$comment`）一律忽略、不告警。

与 CLI / 环境变量映射：

| 设置键 | CLI | 类型/取值 | 默认 | 备注 |
|---|---|---|---|---|
| `agent` | `--agent` | 枚举 | `"pi"` | 调试期可全局切 `null` |
| `timeout` | `--timeout` | 正数（秒） | `300.0` | 按次计（§8.2） |
| `trace` | `--trace` | bool | `false` | |
| `cache.dir` | `--cache DIR` | 路径/null | `null`（→XDG） | 指到项目内时自行 gitignore |
| `cache.disable` | `--cache none` | bool | `false` | CLI `none` 优先于一切 |
| `cache.keep_per_stem` | — | 正整数 | `2` | 仅 GC 行为 |
| `pi.bin` | `--pi-bin` | 路径 | `"pi"` | |
| `pi.connector_path` | `--connector-path` | `"none"`/路径 | `"none"` | 预装 + 显式并存会 A500（去重指引已有） |
| `pi.args` | `--pi-arg`（可多次） | 字符串数组 | `[]` | 拼接语义（§3） |
| `script.path` | `--script` | 路径/null | `null` | 仅 `--agent script` 时消费 |

CLI 侧需区分"显式给出"与"默认"（如 `--agent` 现内置默认 `"pi"` 应改为 `default=None`、事后走 fallback 链），否则显式参数无法覆盖设置文件。

## 5. 潜在配置项全集（按归属分层）

**A. 运行默认（v0.1 提案，见 §4）**：`agent`、`timeout`、`trace`、`cache.*`、`pi.*`、`script.path`。

**B. pi 桥细化（v1+ 候选；Python 侧，低风险）**
- `pi.startup_timeout`：就绪探测（get_state/get_commands）超时——现共用 `timeout`；独立化避免慢启动挤占 pass 预算。
- `pi.stderr_tail_lines`：A500/A503 诊断的 stderr 尾部行数（现常量 40）。
- `pi.barrier_grace`：settled 后响应屏障宽限（现 10s，§16 修正 1 的产物）。

**C. 嵌入形态（v1+ 候选；消费者在连接器 TS 侧，需连接器按同一发现规则读 JSON 或经 spawn env 传递——方案待定）**
- `embed.pcl_bin`：替代 `PCL_BIN`（连接器 spawn pcl）。
- `embed.adoption_timeout`：接续窗口 10s（§8.6 开放问题，即设想的 `--ctx-timeout`）。
- `embed.no_start_grace`：提交存活判定窗 15s（§16 追加 4）。
- `embed.follow`：auto-follow 关闭开关（`false` = 用户切换即按孤儿处理；§8.6 开放问题）。
- `embed.widget_max_lines`：呈现截断行数（现 120）。
- 注：v0.1 连接器继续用环境变量/常量；把 TS 侧拉进设置体系是独立决策（涉及 jiti 读文件与路径一致性）。

**D. 限制与安全（v1+；改动涉及语义，需随 DSL 修订走）**
- `limits.json_depth`：写回值反序列化深度（现 32，DESIGN §6）。
- `limits.write_value_size` / `limits.read_snapshot_size`：读写值体积上限（§15：v0.1 明确不设）。
- 网络/代理：交给 pi 与环境变量，pcl 不自设。

**E. 呈现/输出（v1+，低优先）**
- `output.trace_stream`：`--trace` 增量去向（现 stderr；候选 `file:`）。
- gen 生成源格式（行号尾注等）：**不做**——生成源是协议面（黄金快照），可配即破坏缓存与可调试性契约。

**F. 开发/运维（v0.1 随特性首发）**
- `pcl config`（CLI 子命令）：打印**生效配置及各键来源**（builtin/user/project/CLI，`--show-origin` 风格，范本 `git config --list --show-origin`）；`get/set` 写回工具不做（与手工编辑冲突，收益低）。分层配置的第一支持负担即"这个值从哪来"，故与设置特性**同批交付**而非后补。
- **密封运行（CI/hermetic）**：`PCL_CONFIG_FILE=/dev/null` 仅断开用户级；项目级仍会经模板路径被发现——提供 `--no-project-config`（或 `PCL_NO_PROJECT_CONFIG=1`）跳过项目级发现。

## 6. 明确不配置的项与理由

| 项 | 理由 |
|---|---|
| prompt / `--var` 默认值 | 模板行为不得依赖隐藏状态（DSL §8 哲学；同名多次以末次为准等语义会变味） |
| 模型 / provider / API key | 单一事实源在 pi 的设置与鉴权；透传经 `pi.args`（两处配置必然漂移） |
| 语言语义（trim 空白集、reply 折叠、`text()` 规则、独行消除……） | 规范冻结（DSL §4/§7/§10）；可配即多方言 |
| 生成源格式 / `# pcl:N` 尾注 | 协议面（traceback 回译、黄金快照、缓存 sha 契约） |
| 输出编码 / 换行 | 固定 UTF-8 / `\n`（§10） |
| 上下文 token 存储 | 无映射文件是既定决策（§8）；跨运行持久化归用户 |

## 7. 校验与错误处理

- 文件缺失/目录不存在：该层跳过（不报错）。
- JSON 解析失败：stderr 报错（含文件路径与原因），**exit 1**（配置错误属"未开始执行"，与编译期同码，§10）。
- 已知键类型不符 / 取值非法（如 `agent` 非枚举、`timeout` ≤ 0）：同上 exit 1。
- 未知键：**stderr 警告并继续**（前向兼容：新版加键不炸旧版；拼写错误有提示）。用户级可设 `"strict": true` 把未知键升级为报错（脚本/CI 场景防拼写静默失效）。
- 项目级出现仅用户级键 / `cache.dir` 逃逸：**报错 exit 1**（见 §3.5）。
- `"$comment"`（及 `$` 前缀键）：忽略、不告警。

## 8. 影响面与不变式

- **库形态零影响**：`run_program`/`compile_program`/importer 不读设置（参数显式）；并发多 run 隔离不变（A12）。
- **嵌入形态**：`/pcl run` 拉起的 `pcl` 子进程按模板路径发现项目级设置（同一 `resolve_settings` 代码路径）；连接器自身不读设置（`PCL_BIN`/PATH 维持）。
- **生成源与缓存**：生成源内容只由模板 + 编译器版本决定——设置**不参与缓存 sha**；设置变化不触发重新编译（合理：设置只影响执行环境参数）。
- **就绪探测/错误码**：设置不改变任何错误码语义（A500/A502……映射与消息保持）。

## 9. 实现与测试要点（已落地）

- `pcl/settings.py`：`resolve_settings(entry, no_project=False) -> Settings`（JSONC 剥离 → 逐层校验 → 合并 + 来源追踪；信任模型与相对路径展开内建）。
- `cli.py`：`--agent/--timeout/--script/--pi-bin/--connector-path` 等改为 `default=None` 走 fallback 链；`--cache none` > `cache.disable`、`--cache DIR` > `cache.dir`；`--pi-arg` 追加在设置 `pi.args` 之后；`--no-project-config`；新增 `pcl config [file] [--defaults]`；`python -m pcl` 等价 CLI（A12 补齐）。
- `cache.keep_per_stem` 经 `ensure_compiled(keep_per_stem=…)` 接入 GC。
- 验收清单：
  1. 优先级链（CLI > 项目 > 用户 > 内置）逐键断言；
  2. 项目级向上查找取最近、不合并多层；
  3. `PCL_CONFIG_FILE` 重定向用户级；
  4. 未知键警告、类型错/坏 JSON exit 1；
  5. `--cache none` > `cache.disable`、`--cache DIR` > `cache.dir`；
  6. `pi.args` 拼接顺序（用户 → 项目 → CLI）；
  7. 相对路径按设置文件目录解析；
  8. 库形态（`run_program` 直调）不受任何设置影响；
  9. 嵌入 spawn 的子进程吃到项目级设置；
  10. 生成源与缓存 sha 对设置变化不敏感。

## 10. 版本演进与弃用策略

- 暂不设 `"version"` 字段（YAGNI；未知键宽容 + schema 演进已覆盖绝大多数变更）。若未来需要破坏性迁移再引入，届时旧文件读入即警告。
- **键更名/移除**：至少保留一个 minor 版本的兼容期——旧键读入时 stderr 警告并映射到新键；兼容期满后按未知键处理（警告）。
- **默认值变更**：属行为变更，走 CHANGELOG 显式标注；`pcl config --show-origin` 可核对生效值。

## 11. 开放问题

- 项目级是否需要"仓库根截断"（如遇 `.git` 停止向上）？——倾向不需要（`.pcl/` 目录本身已是显式标记）。
- ~~`pi.args` 重复项语义~~（已关闭）：拼接顺序为用户级 → 项目级 → CLI；同一旗标（如 `--model`）重复时按 pi 命令行"后写胜出"语义生效，文档化即可。
- 连接器（TS）是否纳入同一设置体系（`embed.*`）：涉及 jiti 读文件与两语言路径一致性，建议独立评审。
- 项目信任（trust-on-first-use）机制是否长期引入，以放开项目级执行面键（§3.5 的完整形态）。
- ~~文档中的默认值表与代码常量的漂移防护~~（已关闭）：`pcl config --defaults` 输出权威值；文档表与 `BUILTIN` 常量的一致性由测试锁定（`test_settings.py::test_builtin_matches_doc` 类断言可后续补强）。

## 12. 评审记录

**开源最佳实践评审（2026-09，对照 git/npm/ripgrep/Cargo/pip 及 pi 自身惯例）**：

- 符合项：XDG 用户级+与缓存对称、优先级链（CLI>项目>用户>内置，git/npm 同构）、项目级最近者胜不合并（git 风格）、每个不可配置项附理由、库形态显式参数隔离（12-factor 精神）、未知键宽容（npm 派、跨版本前向兼容）、无机密入配置、相对路径以设置文件目录为基准。
- 修订项（已并入本文）：
  1. **[P0]** 新增 §3.5 键分级与信任模型——项目级配置是随仓库分发的不可信输入，执行面键（`pi.*`/`script.path`）收归仅用户级（先例：npm/pip 供应链教训、git `safe.directory`、pi `project_trust`）；
  2. **[P1]** JSON → **JSONC 子集**（stdlib 预剥离字符串外注释与尾随逗号；tsconfig/VS Code 先例），保留零依赖同时消解无注释痛点；
  3. **[P1]** 新增 `settings.schema.json` 发布（`$schema` 引用 + schemastore；编辑器补全/校验/未知键权威依据）；
  4. **[P1]** `pcl config --show-origin` 从"未来项"提前为**随特性首发**（范本 `git config --list --show-origin`）；补密封运行缺口（`--no-project-config`/`PCL_NO_PROJECT_CONFIG`——`PCL_CONFIG_FILE=/dev/null` 只断用户级）；
  5. **[P2]** 环境变量立场文档化（有意不做逐键 env 及理由；未来插入位 CLI>env>项目>用户）；
  6. **[P2]** 新增 §10 版本演进与弃用策略（更名兼容期、默认值变更走 CHANGELOG）；
  7. **[P2]** 用户级 `"strict": true` 把未知键升级为报错（防拼写静默失效）；
  8. **[P3]** 默认值漂移防护列入开放问题（常量生成文档 / `pcl config --defaults`）。
- 维持原判项：项目级"最近者胜不合并多层"（ripgrep 合并派为另一主流，取可预测者）；入口 `.pcl` 为发现基准（与 §9.3 模块解析一致，模板自包含）；错误信息中文（全项目语言决策，非本方案范畴）。
