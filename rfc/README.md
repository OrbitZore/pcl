# PCL RFCs

> **中文说明**：本目录是面向开发者的规范文档（RFC 范式）。每份 RFC
> 维护中英双版本：`rfc-NNNN-<topic>.zh.md` 为**权威稿**（先写、随实现
> 同步），`rfc-NNNN-<topic>.md` 为英文镜像；分歧即 bug。新 feature
> 必须先提交 RFC——流程见
> [CONTRIBUTING.zh-CN.md](../CONTRIBUTING.zh-CN.md)。用户文档在
> [docs/](../docs/)（注意：仓库根 `README.zh-CN.md`/`CONTRIBUTING.zh-CN.md`
> 用 GitHub 可识别的 `.zh-CN` 后缀，本目录为紧凑起见用 `.zh`——两处
> 指同一语言变体）。

This directory holds the **normative specifications** of PCL, written for
**language implementers and connector developers**. User-facing
documentation lives in [`docs/`](../docs/).

## Numbering & Files

| RFC | Title | Scope |
|---|---|---|
| [0000](rfc-0000-language.md) | Language Definition | Lexical structure, interpolation, directives, pass semantics, error codes |
| [0001](rfc-0001-runtime.md) | Runtime Definition | Compiler pipeline, module layout, bridge abstraction, settings, CLI |
| [0002](rfc-0002-connector.md) | Connector Definition | `/pcl` command family, tools, RPC proxy, session takeover, runtime interface |

## Languages

Every RFC is kept in **two languages**:

- English (normative reference): `rfc-NNNN-<topic>.md`
- Chinese (authoritative draft, `.zh` suffix): `rfc-NNNN-<topic>.zh.md`

The Chinese edition is written first and tracks implementation day-one;
the English edition mirrors it. On any divergence, **file an issue** —
the divergence is a bug, not a feature.

## Status

| Status | Meaning |
|---|---|
| Draft | Under discussion, may change |
| Accepted | Agreed, not yet implemented |
| **Implemented** | Shipped in a release; changes require a new RFC (or a revision RFC `NNNN-rN`) |
| Rejected | Not adopted, kept for the record |

## Process for new RFCs

Any **new feature** — new syntax, new directive, new bridge/connector
capability, or any breaking change — requires an RFC before merging:

1. Copy `rfc-template.md`, pick the next free number.
2. Status `Draft`; open a PR with motivation + specification.
3. After review, status → `Accepted`; implement behind tests.
4. On release, status → `Implemented`.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full contribution
workflow and versioning plan.
