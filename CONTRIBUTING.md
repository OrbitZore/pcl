# Contributing to PCL

Thanks for your interest in contributing! This document covers the basics.

## Getting Started

```bash
git clone https://github.com/USER/pcl.git
cd pcl/pclang
uv venv && uv pip install -e ".[dev]"
python -m pytest -m "not smoke_pi"    # should all pass
```

## Project Structure

```
pcl/
├── pclang/               # Python package (PyPI: pclang, import: pcl)
│   ├── src/pcl/          # Source code
│   │   ├── tlex.py       # Template lexer
│   │   ├── tparse.py     # Parser + static checks
│   │   ├── pygen.py      # Python code generator
│   │   ├── runtime.py    # Runtime API (emit/submit/note/context/...)
│   │   ├── bridge.py     # Bridge abstraction (Null/Script)
│   │   ├── pibridge.py   # Pi bridge (forward + embed)
│   │   ├── importer.py   # .pcl import hooks
│   │   ├── settings.py   # Settings file resolution
│   │   ├── compiler.py   # Compile pipeline + cache
│   │   └── cli.py        # CLI entry point
│   └── tests/            # pytest suite
├── pcl-connector/        # pi connector (TypeScript)
│   └── pi/               # pi-package (install via `pi install`)
│       └── extensions/
│           └── index.ts  # Connector source (no build, jiti loads TS)
├── examples/             # Runnable examples
├── docs/                 # Documentation (mkdocs)
└── .github/workflows/    # CI
```

## Development Workflow

1. **Fork & branch**: Create a feature branch from `main`
2. **Make changes**: Keep commits focused; follow existing code style
3. **Test**: `python -m pytest -m "not smoke_pi"` must pass
4. **Lint**: `ruff check src tests` must pass
5. **Integration** (if bridge/connector changed): `python -m pytest -m smoke_pi` (requires pi + configured model)
6. **Submit PR**: Describe what changed and why

## Code Style

- Python: `ruff` (line length 100, target py310)
- TypeScript: No build step; pi loads TS via jiti
- Tests: pytest, parametrized where possible
- Docs: Update `docs/` and `examples/README.md` when adding features

## Testing Tiers

| Tier | Command | Requirement |
|------|---------|-------------|
| Unit | `pytest -m "not smoke_pi"` | None (always runs in CI) |
| Smoke | `pytest -m smoke_pi` | `pi` binary + configured model |
| Fuzz | `pytest tests/test_fuzz.py` | None (seeded, deterministic) |
| Example | `pytest tests/test_examples.py` | None (compile check only) |

## Adding a New Agent Backend

1. Create `pcl-connector/<backend>/` subdirectory
2. Implement the language contract (pass signaling, read/write tools, context)
3. Add corresponding `IAgentBridge` implementation in Python
4. Add `--agent <backend>` CLI support
5. See `pcl-connector/README.md` for conventions

## Reporting Issues

- **Bugs**: Include minimal `.pcl` reproducer + expected vs actual output
- **Feature requests**: Describe the use case, not just the solution
- **Agent integration**: Specify which agent CLI + version

## License

By contributing, you agree that your contributions will be licensed under the [GNU GPL v3](LICENSE) (GPL-3.0-or-later).
