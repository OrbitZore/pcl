# Examples tour

All in [`examples/`](https://github.com/OrbitZore/pcl/tree/main/examples),
executable (shebang + `chmod +x`).

Run with `pcl run <file.pcl> "<prompt>"` (default `--agent pi`, model
required; connector install in the [Quickstart](quickstart.md)). Add
`--agent null` for pure template debugging.

## goal-loop — Goal-achievement loop

```bash
./goal-loop.pcl "Create a file named hello.txt with content Hello PCL"
```

/goal-style: every pass (act/check) gets a fresh context (`:new`) with
a self-contained prompt (goal + history + round); the `:if` condition
evaluates after writeback — break when done.

## review-prove — Review-and-prove loop

```bash
./review-prove.pcl "Remote work is better than office work" --trace
```

Refines viewpoints until all credible. Shows: `:while` + `:break`,
structured write-back (dict), cross-round state, `:new` isolation,
`$(# … #)` final notes.

## plan-review — Plan self-scoring loop

```bash
./plan-review.pcl "Plan a quarterly tech sharing session"
```

Draft → score loop until 10/10 (or round cap). Shows: threshold
loops, integer write-back validation.

## data-analysis — Structured data fetch

```bash
./data-analysis.pcl
```

Python-side data; the agent fetches via `pcl_read` on demand. Shows:
`:read` snapshots.

## context-session — Context continuation

```bash
./context-session.pcl
```

`:save` → `:new` → `:load` roundtrip with session-memory verification.

## use-library — Template library reuse

```bash
./use-library.pcl --agent null
```

`.pcl`-to-`.pcl` imports, cross-file template functions. Shows: the
load layer (imports never trigger the agent).

## hello — Shebang executable

```bash
./hello.pcl "Quantum entanglement"
```

Minimal `#!/usr/bin/env pcl` + `chmod +x` example.
