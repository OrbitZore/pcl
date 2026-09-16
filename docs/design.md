# PCL 实现设计

- 版本：v0.2（实现态——M0–M4 全量交付 + 设置/示例/模糊测试/bin 命令）
- 架构：`.pcl → 生成 Python 源 → 同解释器执行`；纯 Python 包 + pi 适配（TS 连接器）

---

## 1. 总体架构

```
pcl（纯 Python 包 pclang）
├─ cli.py（run/gen/check/config/version）
│  ├─ tlex → tparse → pygen → 生成 .py（可读、# pcl:行号）
│  ├─ settings.py（用户级/项目级设置发现与合并）
│  └─ runtime.py（emit/text/submit/note/context/save/load/new_ctx/push_sink/pop_sink）
│       │ submit(prompt, reads, writes) ▲ reply / writes
│       ▼
│  IAgentBridge（Null / Script / Pi）───── RPC（stdio JSONL）
│       ▼
│  pi --mode rpc -e <connector>
│       │ pcl-connector/pi/extensions/index.ts
│       │ /pcl 命令族 + pcl_write/pcl_read 工具 + 嵌入代理
│       ▼
│     LLM
```

---

## 2. 编译器

### 2.1 tlex

- `$$` 转义（单遍成对消解）、裸糖 `$prompt`、插值双形式
- 构造闭合：tokenize 增量扫描（字符串/注释感知、括号配平）
- 注释：`${:# …}` / `${# …}` 行界定；注记 `$(# … #)` / 扩展 `$(<delim># … #<delim>)`；上下文 `$(@ … @)` / 扩展 `$(<delim>@ … @<delim>)`
- ASCII 行首/行尾空白剥除、独行消除、CRLF 处理
- R21 `\r` 转义保真（token 级手工提取字符串值，绕过 ast.parse 行结束符归一）

### 2.2 tparse

- AST（dataclass）：Text/Interp/Note/Context/If/While/For/Break/Continue/Function/Return/Pass/Save/Load/NewCtx
- 块配对（P201）、指令参数（P200）、pass 体控制流（P203）、保留名 C300
- 加载层提升判定（import/字面量赋值；AnnAssign 不提升）

### 2.3 pygen

- 发射模型：`${}` 冲刷+独立 emit；`$()` 立即求值暂存织入合并段
- 两相模块布局：加载层 + `main(__pcl_prompt="")`（prompt 序言 + global 并集）
- Note：push_sink → 渲染 body → pop_sink → `note(text)`
- Context：push_sink → 渲染 body → pop_sink → `context(text)`
- 生成源语法检查 → C310（行号映射后报告）

### 2.4 缓存

- `<缓存根>/pcl/<stem>-<sha8>.pcl.py`（sha 含编译器版本）
- 原子落盘（临时文件 + os.replace）、同 stem 保留 2 条（GC）
- importlib 加载复用 `.pyc`

---

## 3. 运行时

| 函数 | 说明 |
|---|---|
| `emit(s)` | 追加当前 sink（pass 体内 = prompt 缓冲） |
| `text(v)` | §10 字符串化（JSON + str() 兜底） |
| `submit(prompt, reads, writes)` | trim → 桥接 → R406/A504/深度检查 → PassResult |
| `note(text)` | 注记：桥支持（embed）→ 会话 custom 条目；否则 → 输出文档 |
| `context(text)` | 上下文注入：forward → steer 排队；embed → context 命令 |
| `save()/load()/new_ctx()` | 上下文三指令 |
| `push_sink()/pop_sink()` | （内部）pass/note/context 的 sink 栈 |

**自动包装**：唯一授权名 + agent 全部键不在授权列表 → 自动嵌套 `{授权名: {平铺 dict}}`。

---

## 4. 桥接层

| 桥 | 用途 |
|---|---|
| NullBridge | `--agent null`：reply=prompt，纯模板调试 |
| ScriptBridge | `--agent script`：JSONL 回放，e2e 测试 |
| PiBridge | `--agent pi`（forward）/--agent embed（嵌入） |

PiBridge 传输：
- forward：`pi --mode rpc` 子进程管道
- embed：自身 stdio（select+os.read 直读 fd，不触碰 BufferedReader 锁）

pass 时序：`/pcl pass {writable, reads, text}` 三键恒出现；`agent_settled` 为唯一 pass 边界；response 仅作屏障（实测：sendUserMessage 发后即忘，response ok 在预检时即发）。

上下文接续（嵌入 §8.6）：模块级桥、绑定分级 L1/L2、接管规则、auto-follow、孤儿路径、A520–A523。

---

## 5. pi 连接器（pcl-connector/pi/）

pi-package（`package.json` + `pi` 清单 + `extensions/index.ts`）：

- `/pcl` 命令族：run（嵌入执行+代理）/ gen/check/config/version（直通）/ pass（机器子命令）
- `pcl_write`/`pcl_read` 工具（名单校验、快照本地应答）
- `before_agent_start`：按需注入读写协议
- `~/.pcl/bin/` 自动命令：递归扫描可执行文件，路径展平注册 `/pcl-<dir>-<name>`
- 嵌入代理表：prompt/get_state/get_commands/get_last_assistant_text/note/context/abort/set_session_name/new_session/switch_session
- 结果呈现：notify 退出码+输出文件路径（不追加全量条目到会话流）

---

## 6. 设置文件

详见 [SETTINGS.md](SETTINGS.md)。

- 用户级 `$XDG_CONFIG_HOME/pcl/settings.json`；项目级 `.pcl/settings.json`
- JSONC 子集（注释/尾随逗号，stdlib 剥离）
- 优先级 CLI > 项目 > 用户 > 内置；`pi.*`/`script.path` 仅用户级（信任模型）
- `pcl config [file] [--defaults]`：打印生效配置及来源

---

## 7. CLI

```
pcl run <file.pcl> [PROMPT…] [选项]
pcl gen/check <file.pcl>
pcl config [file] [--defaults]
pcl version
```

- shebang 直执行：首参数为 .pcl 文件 → 自动展开为 `run <file>`
- `--trace`：stderr 流式诊断（pass 提交/思考增量/pcl_write/轮次边界）
- 退出码：0/1/2/3/130

---

## 8. 测试

- 单元：tlex/tparse/pygen/runtime/settings/pibridge（伪 JSONL 对端）
- e2e：DSL §12 示例 script 桥逐字节断言；嵌入伪宿主 harness
- smoke-pi：真 pi + 真 LLM（forward/embed/auto-follow/A522/A523）
- 模糊：自写 fuzzer（种子可复现），模板编译不崩溃/确定性 + strip_jsonc 不变式
- 示例编译守护：examples/*.pcl 全部 pcl check

---

## 9. 打包与部署

- 分发名 `pclang`（PyPI）；import 名 `pcl`；双入口 `pcl`/`pclang`
- 零运行时依赖；Python ≥3.10；CI 3.10–3.14 × Linux/macOS
- 连接器拆包：`pcl-connector/pi/`（pi-package，`pi install` 三途径）

---

## 10. 实现期实测修正（§16 精简）

1. sendUserMessage 发后即忘 → settled 为唯一 pass 边界
2. 工具参数顶层开放形状被剥空 → values 键嵌套
3. 嵌入读线程不触碰 sys.stdin.buffer（缓冲锁 SIGABRT）
4. `<runtime>`/send_user_message 错误 → A501
5. `/pcl run` 选项切分对齐 argparse（首个 `-` token 起为选项尾）
6. reload 嵌入运行实测良性存活
7. RPC 命令串行 → auto-follow 须 pty 驱动 TUI 测试
8. pcl-connector 子包化 → pi-package 全流程
