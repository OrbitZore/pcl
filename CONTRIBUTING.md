# Contributing to PCL

Thanks for your interest in contributing! 中文版：[CONTRIBUTING.zh-CN.md](CONTRIBUTING.zh-CN.md)（权威稿，英文版为其镜像）。

## RFC Process (every new feature starts with an RFC)

**Every new feature — new syntax, new directives, new bridge/connector
capabilities, any breaking change — requires an RFC before code
merges.** Bugfixes, docs, and tests are exempt.

1. **Draft**: copy [`rfc/rfc-template.md`](rfc/rfc-template.md), take
   the next free number, name it `rfc-NNNN-<topic>.zh.md` (Chinese,
   authoritative) + `rfc-NNNN-<topic>.md` (English mirror). Status `Draft`
2. **Review**: open a PR focused on Motivation / Specification /
   Alternatives. Both language editions **must stay in sync**
3. **Accept**: after review → status `Accepted`; Unresolved Questions
   must be empty
4. **Implement**: implement behind tests; flip the RFC to
   `Implemented`, noting the implementation version
5. **Revise**: changing an Implemented RFC's semantics requires a new
   revision RFC (`NNNN-rN`) — never rewrite specs in place

Current specs: [rfc/](rfc/) — 0000 language / 0001 runtime / 0002
connector.

RFCs are normative, developer-facing documents; user documentation
lives in [docs/](docs/) (`zh/` + `en/`, both must be updated together).

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
└── .github/workflows/    # CI (tests + docs + consistency)
```

## Versioning Plan

SemVer + PEP 440; **starting from alpha**:

| Stage | Sequence | Meaning |
|---|---|---|
| **Alpha (current)** | `0.2.0a1` → `0.2.0a2` → … | First release is an alpha. Language evolves; API/CLI may change |
| Beta | `0.2.0b1` → … | Feature freeze; bugfixes & docs only |
| RC | `0.2.0rc1` → … | Release candidate |
| **Stable** | `0.2.0` | First stable release |
| Later minors | `0.3.0`, `0.4.0`… | New features (each may pre-release aN); in `0.x` minors may break (flagged in CHANGELOG) |
| `1.0.0` | — | Language spec frozen (all RFCs Final); strict semver afterwards |

**Alpha-era stability promise**: the syntax subset shown in
`README.md` is the **stable surface** — no breaking changes during
alpha; language details beyond README (full definition: RFC 0000) may
evolve. Connector protocol (RFC 0002) versions align via the
`pcl version` handshake.

Single source of truth for the version:
`pclang/src/pcl/_version.py` (pyproject reads it dynamically;
`pcl-connector/pi/package.json` is guarded consistent by CI). Tag
releases `v0.2.0a1`-style.

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
- Docs & RFCs: bilingual (`.zh.md` authoritative, `.md` English mirror) — update both or a reviewer will ask

## Reporting Bugs

Open an issue with: the `.pcl` source, the exact command, the error
output (code + message), and `pcl version`. Minimal reproductions get
fixed fastest. Security issues: see [SECURITY.md](SECURITY.md) —
please do not open public issues for those.

## License

By contributing, you agree that your contributions will be licensed
under the [GNU GPL v3](LICENSE) (GPL-3.0-or-later).
