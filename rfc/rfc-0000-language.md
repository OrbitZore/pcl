---
Number: 0000
Title: PCL Language Definition
Status: Implemented
Type: Standards Track
Created: 2026-09-17
Implementation: pclang ≥ 0.2.0
Language: English edition of rfc-0000-language.zh.md
---

# RFC 0000 — PCL Language Definition

## Summary

PCL (Prompt Control Language) is a template DSL for orchestrating LLM
agents. It is a **two-layer language**: the template layer is PCL
(text + `${…}` constructs); the script layer is **real Python** —
expressions, statements, stdlib and third-party libraries all run
natively in the host interpreter. A program's product = output
document (stdout / `-o` file) + side effects (agent interaction,
context switching, Python side effects).

**Non-goals**: custom function library / type system; parallel or
multi-agent orchestration; multi-line constructs (except newlines
inside triple-quoted strings).

## Motivation

Existing agent orchestration either locks your logic inside a
proprietary DSL (no ecosystem, hard to debug) or degenerates into
plain code frameworks (prompts buried in string literals). PCL takes
both worlds: **prompt templates stay readable and control flow is
declarative, but every computation is host Python** — zero learning
cost, zero ecosystem loss, tracebacks pointing back at template lines.

## Specification

### 1. Source files

- UTF-8 (BOM stripped; decode failure → L102); conventional suffix `.pcl`
- First line `#!` ignored (shebang execution: `#!/usr/bin/env pcl` + `chmod +x`)

### 2. Constructs

| Construct | Syntax | Semantics |
|---|---|---|
| **Initiator interpolation** | `${STMTS}` | Construct is a flush point: pure statements flush-then-execute (ordered); expression statements emit `emit(text(EXPR))` standalone, 1:1 line mapping |
| **Merged interpolation** | `$(STMTS)` | Never flushes: expressions evaluated immediately, staged, woven into one emit |
| **Directive** | `${:verb …}` | Control flow / context / pass (§6) |
| **Comment** | `${:# …}` / `${# …}` | Line-delimited (discarded to EOL); must be alone on its line (C305) |
| **Note** | `$(# … #)` | Full template body (recursively tokenized); rendered via `note()` — never enters LLM context |
| **Context injection** | `$(@ … @)` | Full template body; rendered as a standalone user message injected into the agent session — no LLM inference triggered |
| **Escape** | `$$` | → literal `$` (single-pass pairwise) |

**Extended delimiters** (when the body contains a literal closer;
like C++ raw strings):

```text
$(end# note containing #) literal #end)     ← delim="end"
$(tag@ context containing @) literal @tag)  ← delim="tag"
```

- Opening `<delim>#`, closing `#<delim>)` — **strictly symmetric**
  (both markers must be `#`, or both `@`)
- `<delim>` is `\w+`; the closing delimiter must exist ahead in the
  source, otherwise the whole construct falls back to a plain `$()`
  expression

### 3. Closing rules

- `${…}` closes on `}`, `$(…)` on `)` — incremental tokenize scan:
  string/comment aware, bracket balanced
- Newlines inside triple-quoted strings allow constructs to span
  lines; **directives are always single-line**

### 4. Whitespace & line elimination

- Leading/trailing ASCII whitespace (space/tab) stripped per line;
  `\r` stripped with the line terminator
- **Line elimination**: if every construct on a line produces no
  output, the entire line (including the newline) is removed
  (directives, pure-statement interpolations, comments, context
  injections)
- Blank lines are kept (emit `\n`); note lines are **not** eliminated
  (they produce output)

### 5. Interpolation dual forms

| | `${}` initiator | `$()` merged |
|---|---|---|
| Flush | Construct is a flush point | Never flushes |
| Expression stmt | Standalone `emit(text(EXPR))`, 1:1 lines | Evaluated immediately, staged into the merged segment |
| Pure statements | Flush, then execute in order | Execute immediately without breaking the segment |
| Ordering | ✅ side-effect emission ordered w/ surrounding text | Sole exception: side effects during evaluation land before preceding text of the same segment |

- Content: any list of Python **simple statements** (`;`-separated;
  compound statements → C300)
- Expression statement values are **unconditionally** interpolated via
  `text()` (`None` → `null`); assignments/imports execute silently
- Side-effecting calls need a `_ =` prefix to discard the value

### 6. Directives

| Directive | Position | Generated Python |
|---|---|---|
| `${:if EXPR}` / `${:elif}` / `${:else}` / `${:fi}` | any | `if`/`elif`/`else` blocks |
| `${:while EXPR}` … `${:done}` | any | `while` block |
| `${:for X in EXPR}` … `${:done}` | any | `for` block |
| `${:break}` / `${:continue}` | inside loop | `break` / `continue` |
| `${:function NAME(params)}` … `${:endfunction}` | top level | `def NAME(params):` |
| `${:return [EXPR]}` | inside function | `return (EXPR)` |
| `${:pass [:read name] [:write name]}` | any | §7 |
| `${:save name}` / `${:load name}` / `${:new}` | any | `name = save()` / `load(name)` / `new_ctx()` |
| `${:#}` / `${#}` | own line | discarded |

### 7. Pass semantics

```
${:pass :read CTX :write SCORE}
<prompt body: text, interpolation — up to the next directive construct>
```

- The prompt renders into an isolated sink (separate from the output
  document); **auto-commits on the next directive or EOF** (internally trimmed)
- `:read` single-variable snapshot: pre-serialized frozen at pass
  start; the agent fetches by name via `pcl_read`
- `:write` single-variable write-back: the agent writes via `pcl_write`
  - **Auto-wrap**: sole authorized name + every agent key outside the
    authorized list → automatically nested `{authorized: {flat dict}}`
  - Mixed (partly authorized + partly not) → R406
- The reply is emitted into the current sink and stored in `reply`
- Empty prompt skips the bridge call; empty reply → A504;
  unauthorized writes → R406 (checked before A504)
- `:write` values: JSON deserialization depth cap 32 (R400)
- Interpolations inside a pass body must not `break`/`continue`/`return` (P203 — would skip the auto-commit point)

### 8. Context management

- `:save name` → `name = save()`: token = opaque string (pi
  implementation: sessionFile path); empty → A501
- `:load name` → switch to the token session (local existence
  precheck → missing is R430)
- `:new` → fresh anonymous context (previous one auto-persisted)
- Cross-run persistence: the template stores tokens to its own files
  (plain Python I/O)
- Session-replacement semantics in embedded mode: RFC 0002 §3.7

### 9. Modules & import

- `.pcl` ≡ Python module: load layer = `:function` defs + top-level
  imports/literal assignments; `main(prompt)` = the template body
- `import pcl; pcl.install_importer()` then `import mytpl`; inside
  DSL: `${import helpers}`
- `.py` wins over a sibling `.pcl`; **imports never trigger the agent**

### 10. `text()` rules

| Type | Output |
|---|---|
| `str` | as-is |
| `None` | `null` |
| `bool` | `true` / `false` |
| `int` | decimal |
| `float` | round-trip repr |
| `dict/list/tuple` | compact JSON (`ensure_ascii=False`; tuple as list; key collisions degrade to `str(v)`) |
| other | `str(v)` |

### 11. Reserved names

- Runtime reserved (10): `emit` `text` `submit` `save` `load`
  `new_ctx` `push_sink` `pop_sink` `note` `context` — binding any of
  them → C300
- `:function` names `main` / `prompt` / `reply` reserved → C300
- The `__pcl_` prefix is reserved

## Revision History

| Rev | Date | Notes |
|---|---|---|
| r0 | 2026-09-17 | initial (included the `$prompt` bare sugar) |
| [r1](rfc-0000-r1-remove-bare-sugar.md) | 2026-09-17 | **bare sugar removed** — `$prompt` → `$(prompt)` (L103 migration error); construct-table row dropped |

## Error Codes & Exit Codes

| Class | Codes | Exit | Meaning |
|---|---|---|---|
| L | L100–L103 | 1 | Lexical (source/decoding/bare-sugar migration) |
| P | P200–P203 | 1 | Parse (block pairing/args/pass body) |
| C | C300/C305/C310 | 1 | Compile constraints (reserved names/comment placement/generated-source check) |
| R | R400/R405/R406/R409/R430/R431 | 2 | Runtime (evaluation/write-back/authorization/interrupt/context) |
| A | A500–A523 | 3 | Bridge (agent/session/embedded) |
| SIGINT | R409 | 130 | user interrupt |

## Conformance

An implementation (the `pclang` compiler) must:

1. Produce **readable Python source** with `# pcl:N` line annotations
   (tracebacks map back to template lines)
2. Preserve invariants: line elimination must not change the output
   document; `${}` side-effect ordering must hold
3. Emit errors as `file:line:col [code] message` (compile time) or
   code+message (runtime)
4. Follow the exit-code table above

Test suite (`pclang/tests/`): golden snapshots, byte-exact e2e via
the script bridge, deterministic fuzzer (compile never crashes +
compilation determinism).

## References

- RFC 0001 — Runtime Definition
- RFC 0002 — Connector Definition
- [README.md](../README.md) — the stable syntax surface (alpha-era promise)
