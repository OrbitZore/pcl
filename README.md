# PCL — Prompt Control Language

**English** | [简体中文](README.zh-CN.md)

A template DSL for orchestrating LLM agents: **the template layer is PCL, the script layer is real Python**.

[![CI](https://github.com/OrbitZore/pcl/actions/workflows/ci.yml/badge.svg)](https://github.com/OrbitZore/pcl/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pclang.svg)](https://pypi.org/project/pclang/)
[![Python](https://img.shields.io/pypi/pyversions/pclang.svg)](https://pypi.org/project/pclang/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

---

## What is PCL?

PCL compiles `.pcl` templates into readable Python source and executes them in the same interpreter — giving you the full Python ecosystem (including C extensions) with zero third-party dependencies at runtime.

The first supported agent is [pi](https://github.com/earendil-works/pi-coding-agent): forward mode spawns `pi --mode rpc` for pass interaction and context management; embedded mode runs PCL directly inside a pi session via `/pcl` commands.

/goal-style goal-achievement loop (like the /goal feature in other agents — every pass gets a fresh context via `:new`, so each prompt is self-contained: goal + accumulated history + round number):

```text
${ROUND = 0}
${DONE = False}
${W = ""}
${HISTORY = ""}
${MAX = 100}

${:while ROUND < MAX}
    ${ROUND = ROUND + 1}

    ${:new}
    ${:pass :write W}
    Executor (round $(ROUND)/$(MAX)). Fresh context — everything you need is below.
    Task goal: $(prompt)
    Actions so far:
    $(HISTORY if HISTORY else "(none yet — round 1)")
    Take the next action, then call pcl_write exactly once with:
    {"W": "one-line action summary"}

    ${:new}
    ${HISTORY = HISTORY + (W if isinstance(W, str) else str(W)) + "\n"}
    ${:pass :write W}
    Inspector (round $(ROUND)/$(MAX)). Fresh context — judge from the evidence below.
    Task goal: $(prompt)
    Actions so far:
    $(HISTORY)
    Call pcl_write exactly once with:
    {"W": {"done": true/false, "note": "one-line verdict"}}

    ${:# the :if condition evaluates after writeback — W is Pass 2's result}
    ${:if isinstance(W, dict) and W.get("done")}
        ${DONE = True}
        ${:break}
    ${:fi}
    $(# Round $(ROUND) — ⏳ in progress #)
${:done}

${:if DONE}
$(# 🎉 Goal achieved in round $(ROUND)/$(MAX)#)
${:fi}
```

## Stability

Pre-1.0, starting from alpha (`0.2.0a1` — see the
[versioning plan](CONTRIBUTING.md#versioning-plan)):

- **The syntax shown in this README is the stable surface** — no
  breaking changes during alpha
- Language details beyond it (full definition:
  [RFC 0000](rfc/rfc-0000-language.md)) may evolve
- Connector protocol versions align via the `pcl version` handshake

## Install

```bash
pip install pclang        # or: pipx install pclang / uvx pclang
```

Requires Python ≥ 3.10. Zero runtime dependencies.

For the pi connector (forward `--agent pi` and embedded `/pcl` commands):

```bash
pi install git:github.com/OrbitZore/pcl --directory pcl-connector/pi
# or after PyPI release: pi install npm:pcl-connector-pi
```

## Quick Start

```bash
# Pure template debugging (no LLM needed)
pcl run examples/demo.pcl "Why is the sky blue?" --agent null

# With a real agent
pcl run examples/demo.pcl "Why is the sky blue?" --agent pi

# Watch progress in real time
pcl run examples/review-prove.pcl "Why can't high-speed rail use ballasted track?" --trace

# View generated Python source
pcl gen examples/demo.pcl
```

More examples in [examples/](examples/).

## Documentation

| Page | Description |
|------|-------------|
| [Quickstart & Guide](docs/en/index.md) | User docs (English / 中文) |
| [Language Reference](docs/en/language.md) | Cheat sheet: constructs, directives, pass semantics |
| [RFCs](rfc/README.md) | Normative specs: language / runtime / connector |
| [Settings](docs/en/settings.md) | User-level and project-level configuration |
| [Examples](examples/) | Runnable scenarios: loops, context, data analysis, library reuse |

## Key Concepts

| Concept | Syntax | What it does |
|---------|--------|--------------|
| Interpolation | `${expr}` / `$(expr)` | Emit expression value (initiator vs merge) |
| Control flow | `${:if}` `${:for}` `${:while}` | Python-equivalent blocks |
| Agent pass | `${:pass :write VAR}` | One LLM interaction round with structured write-back |
| Context | `${:save ctx}` `${:load ctx}` `${:new}` | Session management (save/switch/create) |
| Note | `$(# text #)` | Rendered annotation — never enters LLM context |
| Context inject | `$(@ text @)` | Injects as user message without triggering inference |
| Raw text | `${r"""…"""}` | Multi-line literal, no interpolation |

## Development

```bash
git clone https://github.com/OrbitZore/pcl.git
cd pcl/pclang
uv venv && uv pip install -e ".[dev]"
python -m pytest                    # unit + e2e tests
python -m pytest -m smoke_pi       # integration (requires pi + model)
ruff check src tests                # lint
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines (Chinese edition: [CONTRIBUTING.zh-CN.md](CONTRIBUTING.zh-CN.md)).

## License

[GPL-3.0](LICENSE)
