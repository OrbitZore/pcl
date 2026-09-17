# FAQ

## R406 (unauthorized write) mid-run?

The agent wrote names not declared via `:write`. Two cases:

1. A fully flat dict (`{"done": true}`) gets **auto-wrapped** when all
   keys are unauthorized — the error means it was a **mix** (authorized
   + others)
2. State the format explicitly in the prompt: "call pcl_write exactly
   once with {"W": {...}}" (nested under the authorized name), plus
   "do not call it again afterwards"

## `${X = W.get(...)}` inside a pass sees a stale value?

The pass body renders **before** the commit — the write-back hasn't
happened yet. Put post-processing outside the pass body, past the next
directive (e.g. after `${:new}`/`${:if}`), or use a `:if` condition
expression (evaluated post-writeback). See [Guide · post-writeback
processing](guide.md#Post-writeback-processing-the-directive-boundary).

## C305: comment must be alone?

`${:# …}` is line-delimited and needs its own line (indentation ok).
For inline remarks use plain Python: `${_ = None  # note}`.

## No agent / no model — how do I debug?

```bash
pcl run --agent null file.pcl "test"   # reply = prompt verbatim
```

All template logic (interpolation, loops, branches) still runs.

## See the generated Python?

```bash
pcl gen file.pcl
```

Readable source with `# pcl:N` line annotations; error tracebacks map
back to template lines too.

## The agent seems to "forget" after `:new`?

`:new` starts a fresh session — **all history cleared** (including
`$(@ @)` injections). Feature, not bug: post-`:new` prompts must be
self-contained. Drop `:new` to keep history.

## What is `$(prompt)`?

The first positional argument: `pcl run x.pcl "task"` →
`prompt = "task"`. Bare sugar `$(prompt)` ≡ `$(prompt)`; default `""`.

## Dicts print as JSON in output?

`text()` rules: dict/list/tuple → compact JSON
(`ensure_ascii=False`), `None` → `null`, `bool` → `true/false`.
Custom formats: `json.dumps(..., indent=2)` yourself.

## What does `:new` do in embedded runs (/pcl run)?

It switches **your current pi session** (the old one auto-persists).
Takeover rules guard this: auto-follow, binding degradation A523,
cross-cwd rejection. See
[RFC 0002 §7](https://github.com/OrbitZore/pcl/blob/main/rfc/rfc-0002-connector.md).

## Exit codes 1/2/3?

1 = compile-time (L/P/C), 2 = runtime (R), 3 = bridge (A),
130 = interrupt. Full table in the [Language Reference](language.md#Error-codes).

## How do I contribute a feature?

Write an RFC first — see
[CONTRIBUTING](https://github.com/OrbitZore/pcl/blob/main/CONTRIBUTING.md).
