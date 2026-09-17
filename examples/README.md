# PCL Examples

**English** | [简体中文](README.zh-CN.md)

Runnable examples organized by scenario. Run with
`pcl run <file.pcl> "<prompt>"` (default `--agent pi`, model required;
connector install in the main [README](../README.md)). Add
`--agent null` for pure template debugging (reply = prompt verbatim,
no LLM).

| Example | Scenario | Key mechanics |
|---|---|---|
| [goal-loop.pcl](goal-loop.pcl) | **Goal-achievement loop** (like /goal in other agents) | Two passes per round (act + check), each in a fresh context (`:new`) with a self-contained prompt (goal + history + round); `:break` when done |
| [review-prove.pcl](review-prove.pcl) | **Review-and-prove loop until all claims are credible** | `:while` + `:break`, structured write-back (string array), cross-round state (PENDING) |
| [plan-review.pcl](plan-review.pcl) | **Plan + self-scoring loop, until 10/10** | `:while` threshold loop, integer write-back validation (bool-trap guard), round cap |
| [data-analysis.pcl](data-analysis.pcl) | Structured data on demand | Python-side data, `:read` snapshot, agent fetches via `pcl_read` (not inlined in prompt) |
| [context-session.pcl](context-session.pcl) | Context continuation | `:save`/`:new`/`:load` roundtrip with session-memory verification |
| [use-library.pcl](use-library.pcl) + [greetlib.pcl](greetlib.pcl) | Library reuse | `.pcl`-to-`.pcl` `import`, load layer (imports never trigger the agent), cross-file template functions |
| [hello.pcl](hello.pcl) | Executable script | shebang `#!/usr/bin/env pcl` + `chmod +x` → `./hello.pcl "topic"` |

## Quick start

```bash
# ① No agent needed (pure template rendering)
pcl run use-library.pcl --agent null

# ② Goal loop (2 LLM calls per round; stops when achieved)
pcl run goal-loop.pcl "Create a file named hello.txt with content Hello PCL" --trace

# ③ Review/plan loops (multi-round, built-in caps)
#    Replies land on stdout only at each round's end — for long loops
#    prefer --trace on stderr for live progress:
#    pass submissions / thinking & text deltas (dimmed) / pcl_write / turn ends
pcl run review-prove.pcl "Why can't high-speed rail use ballasted track?" --trace
pcl run plan-review.pcl "Plan a quarterly tech sharing session for a team of 10" --trace

# ④ Data / context
pcl run data-analysis.pcl
pcl run context-session.pcl

# Inspect the generated Python of any example
pcl gen review-prove.pcl
```

## Direct execution

Every example carries a shebang (`#!/usr/bin/env pcl`) and the
executable bit (`+x`) — run directly:

```bash
./goal-loop.pcl "Create a file named hello.txt with content Hello PCL"
./review-prove.pcl "Why can't high-speed rail use ballasted track?" --trace
./plan-review.pcl "Plan a quarterly tech sharing session for a team of 10"
./context-session.pcl
./data-analysis.pcl
./use-library.pcl --agent null       # pure template (no LLM)
./hello.pcl "Quantum entanglement"
```

Argument pass-through: `./script.pcl [PROMPT…] [options…]` ≡
`pcl run script.pcl [PROMPT…] [options…]`.

## Tips

- **stdout = the output document** (text/interpolations/per-round
  replies, landing at round end); **stderr = diagnostics** (errors,
  live `--trace` progress); exit codes 0/1/2/3/130 (ok / usage &
  compile / runtime / bridge / interrupt);
- Cross-run continuation: store the token from `:save` into a file,
  then next run `${cx = open(...).read().strip()}` + `${:load cx}`
  (the RFC 0000 §8 recipe);
- Every example is compile-guarded by `tests/test_examples.py`
  (equivalent to `pcl check`).
