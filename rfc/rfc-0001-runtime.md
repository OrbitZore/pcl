---
Number: 0001
Title: PCL Runtime Definition
Status: Implemented
Type: Standards Track
Created: 2026-09-17
Implementation: pclang ≥ 0.2.0
Language: English edition of rfc-0001-runtime.zh.md
---

# RFC 0001 — Runtime Definition

## Summary

Defines the execution-layer contract of PCL: the compilation pipeline
(`.pcl` → readable Python source), the two-phase module layout, the
sink stack and output model, the submit protocol, the bridge
abstraction, caching, the settings system, and the CLI. Language
semantics live in RFC 0000; this RFC specifies the **structural
contract implementations must satisfy**.

## Motivation

"Compile to host language, then execute" is PCL's core promise: users
get readable, debuggable, cacheable Python source. Every stage
(compilation, caching, runtime API, bridging) needs explicit
invariants, otherwise "readable Python" degrades into an opaque
bytecode equivalent.

## Specification

### 1. Architecture

```
pcl (pure-Python package pclang, ≥3.10, zero runtime deps)
├─ cli.py (run/gen/check/config/version + shebang expansion + --trace)
├─ compiler.py (tlex → tparse → pygen pipeline + cache)
├─ runtime.py (emit/text/submit/note/context/save/load/new_ctx/
│             push_sink/pop_sink)
└─ bridge.py / pibridge.py (IAgentBridge: Null / Script / Pi)
        │ submit(prompt, reads, writes) ▲ PassResult(reply, writes)
        ▼
     agent (first adapter: pi — see RFC 0002)
```

### 2. Compilation pipeline

| Stage | Responsibility | Key invariants |
|---|---|---|
| **tlex** | source → token stream: `$$` escapes, bare sugar, interpolation dual forms, recursive tokenization of notes/context injections, whitespace stripping, line elimination, CRLF handling | Positions attributable to the source throughout; `\r` fidelity (bypasses ast.parse line-ending normalization) |
| **tparse** | tokens → AST (dataclasses): block pairing (P201), argument checks (P200), pass-body control flow (P203), reserved names (C300), load-layer promotion | AST nodes carry `line/col`; load layer = `:function` defs + top-level imports/literal assignments (AnnAssign not promoted) |
| **pygen** | AST → Python source: emission model (`${}` flush + standalone emits; `$()` staged weaving), two-phase layout, Note/Context wrapped in the sink stack | Generated source carries `# pcl:N` line annotations; syntax check failure → C310 (reported after line mapping) |

### 3. Two-phase module layout

```python
# prologue: imports + constants + __pcl_prompt declaration
# load layer: :function defs + top-level imports/literal assignments
#             (executed once on module import)
def main(__pcl_prompt=""):
    global …   # union of main's binding targets + reply + :write names
    …          # the template body
```

- Module-level `global` union: `reply`, `:write` names, every binding
  target inside `main` (function-local bindings excluded)
- `prompt` declared in the prologue, default `""`; `$prompt` /
  `$(prompt)` reads it

### 4. Sink stack & output model

- `push_sink()` / `pop_sink()` maintain the sink stack; `emit(s)`
  appends to the current top
- Three consumers: pass prompts (isolated from the output document),
  note bodies, context-injection bodies
- The output document = `stdout` or the `-o` file; pass replies are
  emitted into the current sink

### 5. Submit protocol

```python
submit(prompt, reads, writes) -> PassResult(reply, writes)
```

- The prompt is trimmed first; an empty prompt skips the bridge entirely
- Post-bridge validation (fixed order):
  1. Unauthorized writes R406 (incl. the auto-wrap rule: sole
     authorized name + every key unauthorized → wrapped)
  2. Write-back depth ≤ 32 (R400)
  3. Empty reply A504
- `submit` blocks until the agent finishes the turn (pi:
  `agent_settled`, see RFC 0002)

### 6. Bridge abstraction

`IAgentBridge` contract:

| Method | Semantics |
|---|---|
| `submit(prompt, reads, writes)` | Submit one pass; returns `PassResult` |
| `save()` / `load(token)` / `new_ctx()` | The three context directives |
| `note(text) -> bool` | Note: bridge-supported (embed) → session entry, returns True; otherwise falls back to the output document |
| `context(text)` | Context injection (forward → steer; embed → context command) |

Built-in implementations:

| Bridge | Use | Behavior |
|---|---|---|
| `NullBridge` | `--agent null` | reply = the prompt verbatim; pure template debugging |
| `ScriptBridge` | `--agent script` | JSONL replay (reply/writes consumed in order); e2e tests |
| `PiBridge` | `--agent pi` / `--agent embed` | see RFC 0002 |

### 7. Cache

- Path: `<cache-root>/pcl/<stem>-<sha8>.pcl.py` (sha covers source
  content + compiler version)
- Atomic persistence: temp file + `os.replace`
- Keep the 2 most recent per stem (GC); a hit skips compilation and
  reuses the `.pyc` via importlib
- `--cache none` (one-off) or `cache.disable` (settings)

### 8. Settings system

- User-level: `$PCL_CONFIG_FILE` or `$XDG_CONFIG_HOME/pcl/settings.json`
- Project-level: the **nearest** `.pcl/settings.json` walking up from
  the entry `.pcl` file
- JSONC subset (comments/trailing commas stripped in stdlib; TOML
  rejected — no `tomllib` on 3.10)
- Precedence: CLI > project > user > built-in defaults; shallow
  per-section merge; `pi.args` arrays concatenate
- **Trust model**: `pi.*` / `script.path` are user-level only — a
  project file is untrusted input shipped with the repo; executable
  keys at project level → exit 1 (supply-chain defense)
- **CLI-only**: library forms (`run_program`/importer) never read
  settings; callers pass explicit arguments

### 9. CLI

```
pcl run <file.pcl> [PROMPT…] [options]  # compile + execute
pcl gen/check <file.pcl>                # emit source / compile-only check
pcl config [file] [--defaults]          # print effective config + sources
pcl version                             # version + protocol handshake
```

- Shebang expansion: first arg being a `.pcl` file implies `run <file>`
- `--trace`: streaming stderr diagnostics (pass submission / thinking
  deltas / pcl_write / turn boundaries)
- `python -m pcl` equivalent entry
- Exit codes: 0 ok / 1 compile-time (L/P/C) / 2 runtime (R) /
  3 bridge (A) / 130 SIGINT

### 10. Test strategy

| Layer | Coverage |
|---|---|
| Unit | tlex/tparse/pygen/runtime/settings/pibridge (fake JSONL peer) |
| e2e | byte-exact assertions via the script bridge; embedded fake-host harness |
| smoke-pi | real pi + real LLM (forward/embed/auto-follow/A522/A523), marked `smoke_pi` |
| Fuzz | homegrown fuzzer (reproducible seeds): never crash + determinism + strip_jsonc invariants |
| Examples | every `examples/*.pcl` passes `pcl check` |

## Conformance

Alternative runtime implementations must provide: readable generated
Python (line-annotated), the exit-code table, the submit validation
order, the settings trust model, atomic caching. Language semantics
per RFC 0000.

## References

- RFC 0000 — Language Definition
- RFC 0002 — Connector Definition (PiBridge ↔ connector protocol)
