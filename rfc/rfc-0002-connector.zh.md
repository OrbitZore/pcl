---
Number: 0002
Title: PCL Connector Definition
Status: Implemented
Type: Standards Track
Created: 2026-09-17
Implementation: pcl-connector/pi ≥ 0.2.0
---

# RFC 0002 — 连接器定义（Connector）

## Summary

定义 agent 侧连接器契约：连接器是宿主 agent（首个为 pi）内的扩展，
实现 `/pcl` 命令族、`pcl_write`/`pcl_read` 工具、RPC 代理表与
会话接续规则；并定义**连接器与执行层（RFC 0001）之间的接口**。
多后端准备：每个宿主 agent 一个子目录（`pcl-connector/<backend>/`）。

## Motivation

执行层（Python）不直接理解任何 agent——全部交互经桥接协议。连接器
是协议的 agent 侧端点：把 PCL 的 pass 信令翻译成宿主会话操作，把
宿主工具翻译成 PCL 写回。契约明确才能保证：多后端可替换、协议
版本可协商、嵌入/正向两形态行为一致。

## Specification

### 1. 两形态

| 形态 | 启动 | 传输 | 会话 |
|---|---|---|---|
| **forward** | `pcl run --agent pi` 拉起 `pi --mode rpc -e <connector>` 子进程 | 子进程 stdio JSONL（PCL 侧 select+os.read 直读 fd，不触碰 BufferedReader 锁） | PCL 独占 |
| **embed** | 用户在 pi 会话内 `/pcl run <file.pcl>` | 执行层子进程（`pcl run --agent embed -o <tmp>`）经自身 stdio 与宿主连接器对话 | **用户的当前会话** |

### 2. `/pcl` 命令族

| 子命令 | 语义 |
|---|---|
| `run <file.pcl> [PROMPT…] [选项…]` | 嵌入执行：waitForIdle → spawn `pcl run … --agent embed -o <tmp>` 并代理协议 |
| `gen`/`check`/`config`/`version` | 纯 CLI 直通（spawn 捕获 stdout 呈现） |
| `pass`（机器子命令，不进补全） | 每 pass 唯一信令：`/pcl pass {payload}`；payload 三键恒出现（§5） |

连接器是**唯一注册的命令入口**——人类命令面板只出现 `/pcl`。

### 3. 工具

| 工具 | 契约 |
|---|---|
| `pcl_write` | 参数 `{"values": {变量名: JSON 值}}`（命名键 values 承载——宿主校验层会剥顶层开放形状）；**名单先行拒绝**：越权名直接工具层报错，agent 当轮重试；空 values 报错 |
| `pcl_read` | 读 pass 开始时的变量快照（本地应答，不触发 LLM）；越名报错并列出可读名 |

### 4. 协议注入

`before_agent_start`（宿主事件）：仅当当前 pass 存在 read/write 名时，
向本轮 system prompt 链式追加 pcl_write/pcl_read 使用说明（不落
会话）。

### 5. pass 信令

- payload：`{"writable": [...], "reads": {...}, "text": "..."}`
  ——**三键恒出现**（即使空）
- 传递路径：连接器登记白名单/快照 → `pi.sendUserMessage(text)`
  入当前会话（缺省不展开；`/` 开头的 pass 文本免疫——不会被子命令解析）
- **`agent_settled` 是唯一 pass 边界**：sendUserMessage 发后即忘
  （response 在预检时即发，不表示完成）
- 写回收集：工具执行事件流中的 `pcl_write` 调用按名合并

### 6. RPC 代理表

嵌入形态下，执行层经连接器代理宿主 RPC：

| 命令 | 用途 |
|---|---|
| `prompt` / `get_state` / `get_commands` | 就绪探测、状态 |
| `get_last_assistant_text` | reply 提取（失败 A502 容忍，回落缓存） |
| `note` | 注记 → `appendEntry("pcl-note")` 会话自定义条目（不进 LLM 上下文） |
| `context` | 上下文注入 → `sendMessage(triggerTurn=false)`（进上下文不触发推理） |
| `abort` | 中断当前轮 |
| `set_session_name` / `new_session` / `switch_session` | 上下文三指令映射（§7、§8） |

### 7. 上下文接续（嵌入形态）

`:new`/`:load` 涉及**宿主会话替换**：

- **绑定分级**：L1（事件上下文）→ L2（命令上下文，可做会话操作）；
  `/pcl` 任意子命令以当前命令 ctx 升级回 L2
- **接管规则**（session_shutdown）：
  - quit → 先关 stdin（执行层读到 EOF 正常收尾）
  - reload → broken-pipe，桥标记孤儿
  - **new/resume/fork 且非桥发起** → 等待新实例接管（auto-follow，
    10s 时限；超时 → 在途命令回 A52x embed-orphaned）
- auto-follow 后 L1 绑定收到上下文操作 → **A523**（引导：执行任一
  /pcl 命令恢复，或改用正向 CLI）
- `switch_session` **跨 cwd 拒绝**（embed-cross-cwd）：模块必重载、
  桥必孤儿，明确引导走正向 CLI
- `set_session_name`：embed 下执行层不发（不重命名宿主会话）；
  forward 下 save() 顺手改名 `pcl:<stem>` 便于 /resume 辨识

### 8. `~/.pcl/bin/` 自动命令

- 递归扫描可执行文件，路径展平注册 `/pcl-<dir>-<name>`
- **一律作为 pcl 脚本经 `/pcl run` 同路径嵌入当前会话运行**
  （embedded，从不 spawn 文件本身）
- 参数透传为 `run` 的位置参数

### 9. 多后端扩展

- 目录约定：`pcl-connector/<backend>/`（首个：`pi/`）
- 每后端实现本 RFC §2–§8 的等价物（命令族/工具/代理表/接续规则
  可按宿主能力裁剪，但 pass 信令三键与 settled 边界不可妥协）
- 错误码族 A520–A523 保留给嵌入形态孤儿/降级场景

## Connector ↔ Runtime Interface

执行层（RFC 0001 `IAgentBridge`）与连接器之间的线上协议：

| 方向 | 帧 | 语义 |
|---|---|---|
| runtime → connector | `{"type": "/pcl pass", payload 三键}` | 提交 pass |
| connector → runtime | 工具执行事件流（pcl_write/pcl_read 调用与结果） | 写回通道 |
| connector → runtime | `agent_settled` | pass 边界（唯一） |
| runtime → connector | §6 代理表 RPC | 会话/上下文操作 |
| connector → runtime | RPC response（success/cancelled/reason） | 操作结果（A50x/A52x 归因） |

协议握手：`pcl version` 打印执行层版本 + 目标连接器路径（R16 诊断）。

## Conformance

连接器实现必须：pass 信令三键恒出现、settled 唯一边界、名单先行
拒绝、嵌入代理表语义对齐（cancelled→A501、跨 cwd 拒绝、L1 降级
A523）、`~/.pcl/bin/` 一律 embedded。

## References

- RFC 0000 — Language Definition（pass/上下文指令语义）
- RFC 0001 — Runtime Definition（IAgentBridge、submit 协议）
