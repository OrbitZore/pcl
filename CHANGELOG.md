# 更新日志

本项目的全部显著变更记录于此。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)；发布序列从 **alpha** 起步
（版本计划见 [CONTRIBUTING](CONTRIBUTING.zh-CN.md#versioning-plan版本号计划)）。

## [Unreleased]

### 变更（破坏性）

- **移除 `$prompt` 裸糖**（[rfc-0000-r1](rfc/rfc-0000-r1-remove-bare-sugar.zh.md)）：
  模板内注入 prompt 一律 `$(prompt)`；源码出现 `$prompt` 报 **L103**
  （消息含迁移指引）。`$prompts`/`$$prompt` 等非精确匹配不受影响。
  仓库内模板与文档已全量替换

### 变更

- **发布序列调整为 alpha 起步**：计划首发 `0.2.0a1`（PEP 440 alpha），此后
  `0.2.0aN → 0.2.0bN → 0.2.0rcN → 0.2.0`；此前开发版本号 `0.2.0.dev0`
  不再发布
- 许可证 MIT → **GPL-3.0-or-later**
- 规范文档体系重组：`docs/dsl.md`+`docs/design.md` → [rfc/](rfc/)
  （0000 语言 / 0001 执行层 / 0002 连接器，中英双语）；用户文档重组为
  [docs/zh](docs/zh) + [docs/en](docs/en)
- 连接器 `~/.pcl/bin/` 自动命令改为一律 embedded（从不 spawn）

## [0.2.0.dev0] - 2026-09-16

### 新增

- **设置文件（用户级/项目级）**（规范：[RFC 0001 §8](rfc/rfc-0001-runtime.zh.md)；用户文档：[docs/zh/settings.md](docs/zh/settings.md)）：
  - `pcl/settings.py`：JSONC 子集（字符串外注释与尾随逗号，stdlib 剥离且
    行号不失真）；发现（`$PCL_CONFIG_FILE`/XDG 用户级；入口 `.pcl` 向上最近
    `.pcl/settings.json` 项目级；`PCL_NO_PROJECT_CONFIG`）；合并（内置 ←
    用户 ← 项目、节内浅合并、`pi.args` 拼接、逐键来源追踪）
  - **信任模型**：`pi.*`/`script.path` 仅用户级（项目级出现 → exit 1）；
    项目级 `cache.dir` 须相对且不逃逸项目目录
  - CLI 接线：`--agent/--timeout/--script/--pi-bin/--connector-path` 走
    fallback 链（CLI 显式 > 项目级 > 用户级 > 内置）；`--pi-arg` 追加在设置
    `pi.args` 后；`--cache none` > `cache.disable`
  - `pcl config [file] [--defaults]`：打印生效设置及各键来源
  - `settings.schema.json` 随 wheel 分发（`$schema` 引用即得编辑器校验）
  - `cache.keep_per_stem` 设置项接入编译器缓存 GC
  - `python -m pcl` 等价 CLI（DESIGN A12 补齐）
  - 连接器 `/pcl config` 进直通命令族
- **模糊测试**（RFC 0001 §10）：自写 fuzzer、零依赖、固定种子可复现
  （`PCL_FUZZ_ITERS`/`PCL_FUZZ_SEED` 覆盖）——模板编译不崩溃/确定性，
  JSONC 剥离不崩溃/合法 JSON 不变/字符串免疫

### 结构调整

- **pcl-connector 子包化**（多 agent 后端准备）：`index.ts` → `pi/extensions/index.ts`，
  `pi/` 成为独立 pi-package（`pcl-connector-pi`：`pi` 清单 + peerDeps）；
  pi 包全流程打通并实测（`pi install` 本地路径 / `pi -e` 临时 / `pi remove`）；
  `--connector-path` 接受包目录或 extensions/index.ts；后续后端各自成
  `pcl-connector/<backend>/` 子包（约定见 pcl-connector/README.md）

### 修复

- `--` 分隔符改为版本无关预处理：argparse 对「子命令 + `nargs="*"`
  位置参数」的 `--` 语义随 Python 版本漂移（≤3.13 报无法识别的参数、
  3.14 并入位置参数）——首个 `--` 后的 token 一律并入 PROMPT（与连接器
  `/pcl run` 切分规则一致）；本地矩阵 3.10–3.14 全绿
- 深嵌套（未闭合 `:if` 链等）泄漏 `RecursionError` → 干净的 C310
  「嵌套过深」（模糊测试发现）
- `_find_closer` 未捕获 `UnicodeDecodeError`（C tokenizer 对病态输入的
  再解码失败）→ L101（模糊测试发现）

## [0.1.0.dev0] - 2026-09-15

v0.1 里程碑 M0–M4 全量交付（DSL/DESIGN 终审冻结版的首个实现）。

### 编译器（M0）

- `tlex`：`$$` 转义（单遍成对消解）、裸糖 `$prompt`、tokenize 增量扫描的
  括号配平闭合、跨行构造仅限三引号字符串、ASCII 空白剥除/独行消除、
  `${:#}` 行界定注释、CRLF 与文件末尾孤立 `\r` 剥离、构造内逐字保留
- `tparse`：AST 与块配对（P200–P203）、保留名 C300、非提升位置
  `import *` C300、加载层提升判定
- `pygen`：插值双形式发射模型（`${}` 发起型冲刷+独立 emit；`$()` 合并型
  立即求值暂存织入）、两相模块布局、reply 尾换行折叠、pass 开启/冻结/
  提交序列、**R21 `\r` 转义保真**（token 级手工提取字符串值）
- `pcl gen/check`、A11 缓存（sha8 原子落盘、同 stem 保留 2 条、`.pyc` 复用）

### 运行时与模块化（M1）

- `pcl/runtime.py`：8 个运行时入口 + `__pcl_freeze`、`text()` JSON+str()
  兜底、submit trim/空跳过/**R406 先于 A504**/深度上限、R400 traceback
  帧回译
- Null/Script 测试桥；`.pcl` import 互操作（meta path 兜底、`.py` 优先、
  `run_program` 模块实例隔离）

### pi 适配（M2）

- `pibridge.py`：`pi --mode rpc` 子进程 + JSONL RPC、`/pcl pass` 三键信令、
  `agent_settled` 边界、上下文三指令（token=sessionFile、`:save` 命名重取、
  `:load` 惰性落盘预检 R430）
- `pcl-connector/index.ts`：`/pcl` 命令、`pcl_write`/`pcl_read` 工具、
  `before_agent_start` 协议注入
- RFC 0000 §13 示例对真 LLM 全链路跑通；实测修正记入 RFC 0002

### 嵌入模式（M3/M4）

- `/pcl run` 命令族 + 协议代理 + stdout 独占；embed 传输（select+os.read
  直读 fd，规避缓冲锁 SIGABRT）
- 上下文接续：模块级桥、绑定分级（L1/L2）、三条接管规则、auto-follow、
  孤儿路径、跨 cwd 预检 A522、L1 降级 A523

### 打包

- PyPI 分发名 `pclang`（import/命令名 `pcl`）、零运行时依赖、
  pcl/pclang 双入口、连接器拆包分发

[Unreleased]: https://github.com/OrbitZore/pcl/compare/HEAD
[0.2.0.dev0]: https://github.com/OrbitZore/pcl/releases/tag/v0.2.0.dev0
