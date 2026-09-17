---
Number: 0003
Title: Versioning Plan
Status: Accepted
Type: Process
Created: 2026-09-17
Language: 中文（权威稿；英文镜像见同名 .md）
---

# RFC 0003 — 版本号计划

## Summary

定义 PCL 的版本命名、发布序列、各阶段退出条件与稳定性分层承诺。
遵循 PEP 440 格式 + 语义化版本（semver）语义，发布序列**从 alpha 起步**，
`1.0.0` 冻结语言规范。

## Motivation

项目即将首次发布（PyPI `pclang` + npm `pcl-connector-pi`）。没有明确的
版本策略，用户无法判断"什么会变、什么不变"；贡献者无法判断"变更该进
哪个版本"；多后端连接器无法对齐协议版本。alpha 起步的理由：功能完整但
未经外部用户大规模验证，过早 stable 会把 bug 修复变成 breaking change。

## Specification

### 1. 命名规则

- **PEP 440** 格式 + **semver** 语义；tag 用 `v` 前缀（`v0.2.0a1`）
- 版本**单源**：`pclang/src/pcl/_version.py`（pyproject 经 dynamic 读取；
  `pcl-connector/pi/package.json` 由 CI consistency job 守护一致）
- PyPI（`pclang`）与 npm（`pcl-connector-pi`）**语义同版本同步发布**；
  预发布分隔符按各自生态惯例：PEP 440 `0.2.0a1` ↔ npm semver `0.2.0-a1`
  （CI consistency 按规范化比较）

### 2. 发布序列

```
现在          0.2.0.dev0（代码态，从未发布，跳过——不进 PyPI）
────────────────────────────────────────────────────
Alpha   0.2.0a1 → a2 → a3 …      首发 = 现有全部成果
Beta    0.2.0b1 → b2 …           特性冻结，只修 bug/文档
RC      0.2.0rc1 → rc2 …         仅致命修复，协议握手冻结
Stable  0.2.0                    首个稳定版
────────────────────────────────────────────────────
Minor   0.3.0 / 0.4.0 …          新特性（各自可走 aN 预发）
1.0.0                           语言规范冻结
```

- **`0.2.0a1`（首发）内容**：M0–M4（编译器/运行时/桥接/嵌入形态）、
  设置系统、`~/.pcl/bin/` embedded 命令、示例集、RFC 体系、双语文档
- **后续 minor 候选方向**（每项走新 RFC，非承诺）：
  - `0.3.0`：语言增强（多 `:write` 变量、pass 参数化、note 子模板行号偏移映射）
  - `0.4.0`：新 agent 后端子包（`claude-code/`、`gemini-cli/`，按 RFC 0002 契约）
  - `0.5.0`：导入生态/缓存/性能
- **`0.x` 期间**：minor 允许破坏性变更——CHANGELOG 显著标注 + 走 RFC 修订

### 3. 阶段退出条件

| 阶段 | 进入 | 退出 |
|---|---|---|
| Alpha | 首发 | README 语法面 ≥30 天无变更；alpha issue 收敛 |
| Beta | 上述满足 | 无 open P0/P1 issue |
| RC | Beta 满足 | rc 期间零致命回归 |
| 0.2.0 | — | — |
| **1.0.0** | RFC 0000/0001/0002 全部 `Final` + ≥2 个稳定 minor 周期 + 连接器协议 v1 冻结 | 此后严格 semver（仅 major 破坏） |

### 4. 稳定性分层承诺

| 层 | 稳定起点 | 说明 |
|---|---|---|
| README 展示语法 | **alpha 起** | 用户可见的最小稳定面 |
| CLI 子命令/退出码/错误码族 | **alpha 起** | 调试脚本与 CI 依赖 |
| RFC 0000 语言全集 | **0.2.0**（beta 冻结） | 规范级承诺 |
| RFC 0001/0002（执行层/连接器协议） | **0.2.0** | 多后端实现按此对齐，握手经 `pcl version` |
| 设置 schema | 加键随时；删键/改语义走 minor + RFC | |

### 5. 发版操作清单

1. 改 `_version.py`（单源；CI 守护 package.json 同步）
2. CHANGELOG：`Unreleased` → 版本号 + 日期，底部链接补全
3. `git tag vX.Y.ZN && git push --tags`
4. `cd pclang && uv build && uv publish`
5. 连接器 `npm publish`（版本同步）；验证 `pcl version` 握手

## Alternatives

- **直接发 0.2.0 stable**：功能完整但缺外部用户验证，拒绝——bug 修复会
  被迫成为 breaking change
- **0.1.0 起步**：版本历史（git/CHANGELOG）已是 0.2 线，回退无意义
- **长期 pre-release（`0.2.0.dev0` 上 PyPI）**：dev 后缀对依赖解析器是
  最弱信号，用户容易误装；alpha/beta/rc 的递进语义更清晰

## Unresolved Questions

（无）

## References

- [PEP 440](https://peps.python.org/pep-0440/)、[semver](https://semver.org/)
- RFC 0000/0001/0002（稳定性承诺的规范载体）
- [CONTRIBUTING.zh-CN.md](../CONTRIBUTING.zh-CN.md)（贡献者视角摘要）
