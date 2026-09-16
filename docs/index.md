# PCL — Prompt Control Language

A template DSL for orchestrating LLM agents: **the template layer is PCL, the script layer is real Python**.

## Why PCL?

- **Zero lock-in**: Your logic is plain Python — import any library, use any tool
- **Readable output**: `.pcl` compiles to readable Python source with line-number annotations (`# pcl:N`), so tracebacks point back to your template
- **Full agent control**: Structured write-back, session context management, multi-round loops — all as first-class language constructs
- **Zero dependencies**: Pure Python ≥3.10, no third-party packages required at runtime

## Quick Example

```text
${SCORE = 0}

${:pass :write SCORE}
Write about: $prompt
Rate your quality (0-10), write to SCORE.

${:if SCORE >= 7}
Passed.
${:else}
Rewrite and rescore.
${:fi}
```

```bash
pcl run demo.pcl "Why is the sky blue?"
```

## Install

```bash
pip install pclang
```

For the pi connector:

```bash
pi install git:github.com/USER/pcl --directory pcl-connector/pi
```

## Next Steps

- [Language Reference](dsl.md) — complete syntax guide
- [Architecture](design.md) — how the compiler and runtime work
- [Settings](settings.md) — configure default agent, timeouts, caching
- [Examples](examples.md) — runnable scenarios
