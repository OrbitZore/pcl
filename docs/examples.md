# Examples

All examples are in the [`examples/`](https://github.com/USER/pcl/tree/main/examples) directory and are executable (shebang + `chmod +x`).

## review-prove — Review loop until all claims are verified

```bash
./review-prove.pcl "Why can't high-speed rail use ballasted track?" --trace
```

Demonstrates: `:while` + `:break`, structured write-back (dict), cross-round state (`BRAINSTORM`/`PENDING`), `$(# … #)` note output.

## plan-review — Plan + self-review loop until 10/10

```bash
./plan-review.pcl "Plan a quarterly tech sharing session for a team of 10"
```

Demonstrates: score threshold loop, integer write-back with bool guard, round cap.

## data-analysis — Structured data via `:read`

```bash
./data-analysis.pcl
```

Demonstrates: Python-side data generation, `:read` snapshot, agent pulls via `pcl_read` (not inlined in prompt).

## context-session — Session save/new/load roundtrip

```bash
./context-session.pcl
```

Demonstrates: `:save` → `:new` → `:load` roundtrip with session memory verification.

## use-library — Library reuse between templates

```bash
./use-library.pcl --agent null
```

Demonstrates: `.pcl` → `.pcl` import, template functions, load layer (import never triggers agent).

## hello — Shebang executable

```bash
./hello.pcl "Quantum entanglement"
```

Demonstrates: `#!/usr/bin/env pcl` + `chmod +x` for direct execution.

## goal-loop — Goal achievement loop

```bash
./goal-loop.pcl "Create a file named hello.txt with content Hello PCL"
```

Demonstrates: `/goal`-style loop (act + check per round), `:while` + `:break` on boolean variable, `$(# … #)` note output, `$(@ … @)` context injection.
