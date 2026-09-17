# Contributing to PCL

Thanks for your interest in contributing! This document covers the
basics: the RFC process for features, the development workflow, and
the versioning plan.

## RFC Process（新特性必须先写 RFC）

**每一个新 feature——新语法、新指令、新桥接/连接器能力、任何破坏性
变更——必须先提交 RFC 再合并代码。** bugfix、文档、测试不需要。

1. **起草**：复制 [`rfc/rfc-template.zh.md`](rfc/rfc-template.zh.md)，
   取下一个空闲编号，命名 `rfc-NNNN-<topic>.zh.md`（中文权威稿）+
   `rfc-NNNN-<topic>.md`（英文镜像）。状态 `Draft`
2. **评审**：开 PR，重点看 Motivation / Specification /
   Alternatives。中文与英文版**必须同步修改**
3. **接受**：评审通过 → 状态 `Accepted`；Unresolved Questions 清空
4. **实现**：带测试实现；相关 RFC 状态改 `Implemented`，标注实现版本
5. **修订**：已 Implemented 的 RFC 需要语义变更 → 开新的修订 RFC
   （`NNNN-rN`），不允许原地改写规范

现有规范：[rfc/](rfc/) —— 0000 语言定义 / 0001 执行层 / 0002 连接器。

RFC 是面向开发者的规范性文档；用户文档在 [docs/](docs/)
（`zh/` + `en/` 双语）。

## Getting Started

```bash
git clone https://github.com/OrbitZore/pcl.git
cd pcl/pclang
uv venv && uv pip install -e ".[dev]"
python -m pytest -m "not smoke_pi"    # should all pass
```

## Project Structure

```
pcl/
├── pclang/               # Python package (PyPI: pclang, import: pcl)
│   ├── src/pcl/          # tlex/tparse/pygen/runtime/bridge/pibridge/...
│   └── tests/            # pytest suite (smoke_pi = real LLM)
├── pcl-connector/        # agent connectors (one dir per backend)
│   └── pi/               # pi-package (TypeScript, jiti-loaded)
├── examples/             # Runnable examples (each must pass pcl check)
├── docs/                 # User docs: docs/zh/ + docs/en/
├── rfc/                  # Normative specs (developer-facing, .zh + .md)
└── .github/workflows/    # CI
```

## Versioning Plan（版本号计划）

完整计划见 [RFC 0003](rfc/rfc-0003-versioning.zh.md)。摘要——遵循
[语义化版本](https://semver.org/) + PEP 440；**从 alpha 开始**：

| 阶段 | 版本序列 | 含义 |
|---|---|---|
| **Alpha（当前）** | `0.2.0a1` → `0.2.0a2` → … | 首个发布即 alpha。语言演进期，API/CLI 可变 |
| Beta | `0.2.0b1` → … | 特性冻结；只修 bug 与文档 |
| RC | `0.2.0rc1` → … | 发布候选 |
| **Stable** | `0.2.0` | 第一个稳定版 |
| 后续 minor | `0.3.0`、`0.4.0`… | 新特性（各自可走 aN 预发）；`0.x` 期间 minor 可含不兼容变更（在 CHANGELOG 标注） |
| `1.0.0` | — | 语言规范冻结（全部 RFC 转 Final）；此后严格遵守 semver |

**Alpha 期稳定承诺**：`README.md` 中展示的语法子集 = **稳定面**——
alpha 阶段保证不发生破坏性变更；超出 README 的语言细节（完整定义见
RFC 0000）可能演进。连接器协议（RFC 0002）以 `pcl version` 握手
信息对齐版本。

版本单源：`pclang/src/pcl/_version.py`（pyproject 经 dynamic 读取；
`pcl-connector/pi/package.json` 由 CI consistency job 守护一致）。发版时
更新单源并打 tag（`v0.2.0a1` 格式）。

## Development Workflow

1. **Fork & branch**: feature branch from `main`
2. **RFC first** (features): see above
3. **Make changes**: keep commits focused; docs (zh + en) and RFCs
   updated in the same PR
4. **Test**: `python -m pytest -m "not smoke_pi"` must pass
5. **Lint**: `ruff check src tests` must pass
6. **Integration** (if bridge/connector changed): `python -m pytest -m smoke_pi` (requires pi + a configured model)
7. **Examples** (if language changed): every `examples/*.pcl` passes `pcl check`
8. **Submit PR**: describe what changed and why; link the RFC if any

## Code Style

- Python: standard library only (runtime); ruff-clean
- TypeScript (connector): no build step — jiti loads `extensions/index.ts` directly
- Docs & RFCs: bilingual (`.zh.md` authoritative, `.md` English mirror) — update both or the CI-minded reviewer will ask

## Reporting Bugs

Open an issue with: the `.pcl` source, the exact command, the error
output (code + message), and `pcl version`. Minimal reproductions get
fixed fastest.

## License

By contributing, you agree that your contributions will be licensed
under the [GNU GPL v3](LICENSE) (GPL-3.0-or-later).
