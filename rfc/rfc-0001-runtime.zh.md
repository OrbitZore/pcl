---
Number: 0001
Title: PCL Runtime Definition
Status: Implemented
Type: Standards Track
Created: 2026-09-17
Language: 中文（权威稿；英文镜像见同名 .md）
Implementation: pclang ≥ 0.2.0
---

# RFC 0001 — 执行层定义（Runtime）

## Summary

定义 PCL 的执行层契约：编译管线（`.pcl` → 可读 Python 源）、两相模块
布局、sink 栈与输出模型、submit 协议、桥接抽象、缓存、设置系统与
CLI。语言语义由 RFC 0000 定义；本 RFC 规定**实现必须满足的结构性
契约**——第三方实现按此对齐。

## Motivation

"编译到宿主语言再执行"是 PCL 的核心承诺：用户拿到的是可读、可
debug、可寄存的 Python 源。这要求执行层的每个环节（编译、缓存、
运行时 API、桥接）都有明确不变式，否则"可读 Python"退化为不透明
的字节码等价物。

## Specification

### 1. 总体架构

```
pcl（纯 Python 包 pclang，≥3.10，零运行时依赖）
├─ cli.py（run/gen/check/config/version + shebang 展开 + --trace）
├─ compiler.py（tlex → tparse → pygen 管线 + 缓存）
├─ runtime.py（emit/text/submit/note/context/save/load/new_ctx/
│             push_sink/pop_sink）
└─ bridge.py / pibridge.py（IAgentBridge：Null / Script / Pi）
        │ submit(prompt, reads, writes) ▲ PassResult(reply, writes)
        ▼
     agent（首个适配：pi，见 RFC 0002）
```

### 2. 编译管线

| 阶段 | 职责 | 关键不变式 |
|---|---|---|
| **tlex** | 源 → token 流：`$$` 转义、裸糖、插值双形式、注记/上下文递归 tokenize、空白剥除、独行消除、CRLF 处理 | 行号/列号自始至终可归因到源；`\r` 保真（绕过 ast.parse 行结束符归一） |
| **tparse** | token → AST（dataclass）：块配对（P201）、参数校验（P200）、pass 体控制流（P203）、保留名（C300）、加载层提升判定 | AST 节点携带 `line/col`；加载层 = `:function` + 顶层 import/字面量赋值（AnnAssign 不提升） |
| **pygen** | AST → Python 源：发射模型（`${}` 冲刷 + 独立 emit；`$()` 暂存织入）、两相布局、Note/Context 的 sink 栈包裹 | 生成源含 `# pcl:N` 行号标注；语法检查失败 → C310（行号映射后报告） |

### 3. 两相模块布局

生成源结构：

```python
# 序言：import + 常量 + __pcl_prompt 声明
# 加载层：:function 定义 + 顶层 import/字面量赋值（模块 import 时执行一次）
def main(__pcl_prompt=""):
    global …   # main 内绑定目标并集 + reply + :write 名
    …          # 模板体
```

- 模块级全局（`main` 的 `global` 并集）：`reply`、`:write` 名、
  main 内一切绑定目标（函数内绑定不进）
- `prompt` 序言声明，缺省 `""`；`$prompt`/`$(prompt)` 读它

### 4. Sink 栈与输出模型

- `push_sink()` / `pop_sink()` 维护 sink 栈；`emit(s)` 追加当前栈顶
- 三个层级使用 sink 栈：pass prompt（隔离于输出文档）、注记体、
  上下文注入体
- 输出文档 = `stdout` 或 `-o` 文件；pass 回复经 `emit` 追加当前 sink

### 5. submit 协议

```python
submit(prompt, reads, writes) -> PassResult(reply, writes)
```

- prompt 先 trim（首尾空白剥除）；空 prompt 直接跳过（不调桥接）
- 桥接返回后校验（顺序固定）：
  1. 越权写入 R406（含自动包装判定：唯一授权名 + 全部键越权 → 包装）
  2. 写回值深度 ≤ 32（R400）
  3. 空回复 A504
- `submit` 阻塞至 agent 本轮结束（pi：`agent_settled` 事件，见 RFC 0002）

### 6. 桥接抽象

`IAgentBridge` 契约：

| 方法 | 语义 |
|---|---|
| `submit(prompt, reads, writes)` | 提交一轮 pass，返回 `PassResult` |
| `save()` / `load(token)` / `new_ctx()` | 上下文三指令 |
| `note(text) -> bool` | 注记：桥支持（embed）→ 会话条目并返回 True；否则回落输出文档 |
| `context(text)` | 上下文注入（forward → steer；embed → context 命令） |

内置实现：

| 桥 | 用途 | 行为 |
|---|---|---|
| `NullBridge` | `--agent null` | reply = prompt 原样；纯模板调试 |
| `ScriptBridge` | `--agent script` | JSONL 回放（reply/writes 逐条消费）；e2e 测试 |
| `PiBridge` | `--agent pi` / `--agent embed` | 见 RFC 0002 |

### 7. 缓存

- 路径：`<缓存根>/pcl/<stem>-<sha8>.pcl.py`（sha 含源内容 + 编译器版本）
- 原子落盘：临时文件 + `os.replace`
- 同 stem 保留最近 2 条（GC）；命中即跳过编译，importlib 复用 `.pyc`
- 缓存可 `--cache none`（禁用）或 `cache.disable`（设置）

### 8. 设置系统

- 用户级：`$PCL_CONFIG_FILE` 或 `$XDG_CONFIG_HOME/pcl/settings.json`
- 项目级：入口 `.pcl` 所在目录向上**最近一个** `.pcl/settings.json`
- 格式 JSONC 子集（stdlib 剥离注释/尾随逗号；TOML 因 3.10 无 tomllib 落选）
- 优先级：CLI > 项目级 > 用户级 > 内置默认；节内浅合并；`pi.args` 数组拼接
- **信任模型**：`pi.*`/`script.path` 仅用户级——项目级文件是随仓库分发的
  不可信输入，出现执行面键 → exit 1（供应链防线）
- **只服务 CLI**：库形态（`run_program`/importer）完全不读设置，调用方显式传参

### 9. CLI

```
pcl run <file.pcl> [PROMPT…] [选项]     # 编译 + 执行
pcl gen/check <file.pcl>                # 生成源 / 仅编译校验
pcl config [file] [--defaults]          # 打印生效配置及来源
pcl version                             # 版本 + 协议握手信息
```

- shebang 展开：首参数为 `.pcl` 文件 → 自动视为 `run <file>`
- `--trace`：stderr 流式诊断（pass 提交/思考增量/pcl_write/轮次边界）
- `python -m pcl` 等价入口
- 退出码：0 成功 / 1 编译期（L/P/C）/ 2 运行期（R）/ 3 桥接（A）/ 130 SIGINT

### 10. 测试策略

| 层 | 覆盖 |
|---|---|
| 单元 | tlex/tparse/pygen/runtime/settings/pibridge（伪 JSONL 对端） |
| e2e | script 桥逐字节断言；嵌入伪宿主 harness |
| smoke-pi | 真 pi + 真 LLM（forward/embed/auto-follow/A522/A523），标记 `smoke_pi` |
| 模糊 | 自研 fuzzer（种子可复现）：编译不崩溃 + 编译确定性 + strip_jsonc 不变式 |
| 示例守护 | `examples/*.pcl` 全部 `pcl check` |

## Conformance

第三方执行层实现必须满足：生成可读 Python（含行号标注）、退出码
表、submit 校验顺序、设置信任模型、缓存原子性。语言语义符合
RFC 0000。

## References

- RFC 0000 — Language Definition
- RFC 0002 — Connector Definition（PiBridge 与连接器的协议细节）
