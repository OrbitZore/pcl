# PCL — Prompt Control Language

**English** | [简体中文](README.zh_CN.md)

A template DSL for orchestrating LLM agents: **the template layer is PCL, the script layer is real Python**.

[![CI](https://github.com/USER/pcl/actions/workflows/ci.yml/badge.svg)](https://github.com/USER/pcl/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/pclang.svg)](https://pypi.org/project/pclang/)
[![Python](https://img.shields.io/pypi/pyversions/pclang.svg)](https://pypi.org/project/pclang/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What is PCL?

PCL compiles `.pcl` templates into readable Python source and executes them in the same interpreter — giving you the full Python ecosystem (including C extensions) with zero third-party dependencies at runtime.

The first supported agent is [pi](https://github.com/earendil-works/pi-coding-agent): forward mode spawns `pi --mode rpc` for pass interaction and context management; embedded mode runs PCL directly inside a pi session via `/pcl` commands.

```text
${ROUND = 0}
${DONE = False}
${MAX = 100}

$(@
Goal: $prompt
Each round: 1) act to progress 2) check if done. Max ${MAX} rounds.
@)

${:while ROUND < MAX}
    ${ROUND = ROUND + 1}

    ${:new}
    ${:pass :read ROUND :write W}
    Act toward the goal (round $(ROUND)). Write to W: {"W": "action summary"}

    ${:new}
    ${:pass :read ROUND :write W}
    Check if goal achieved. Write to W: {"W": {"done": true/false, "note": "reason"}}

    ${:if 1}
    ${DONE = W.get("done") if isinstance(W, dict) else False}
    $(# Round $(ROUND): $(("✅ done" if DONE else "⏳ in progress")) #)
    ${:if DONE}${:break}${:fi}
    ${:fi}
${:done}

${:if DONE}
$(# 🎉 Goal achieved in round $(ROUND)/$(MAX)#)
${:fi}
```

## Install

```bash
pip install pclang        # or: pipx install pclang / uvx pclang
```

Requires Python ≥ 3.10. Zero runtime dependencies.

For the pi connector (forward `--agent pi` and embedded `/pcl` commands):

```bash
pi install git:github.com/USER/pcl --directory pcl-connector/pi
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
| [Language Reference](docs/dsl.md) | Complete syntax: constructs, directives, pass semantics |
| [Design](docs/design.md) | Architecture, compiler pipeline, runtime, bridge layer |
| [Settings](docs/settings.md) | User-level and project-level configuration |
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
git clone https://github.com/USER/pcl.git
cd pcl/pclang
uv venv && uv pip install -e ".[dev]"
python -m pytest                    # unit + e2e tests
python -m pytest -m smoke_pi       # integration (requires pi + model)
ruff check src tests                # lint
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

[MIT](LICENSE)
