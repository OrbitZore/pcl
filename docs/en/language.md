# Language Reference (cheat sheet)

User-facing quick reference. Full normative spec:
[RFC 0000](https://github.com/OrbitZore/pcl/blob/main/rfc/rfc-0000-language.md).

## Constructs

| Construct | Syntax | One-liner |
|---|---|---|
| Initiator interpolation | `${STMTS}` | real Python statements; expression values inserted; 1:1 line numbers |
| Merged interpolation | `$(STMTS)` | same, but woven into the merged segment; good for splicing |
| Directive | `${:verb …}` | control flow / context / pass |
| Comment | `${:# …}` / `${# …}` | discarded to EOL; **own line only** |
| Note | `$(# … #)` | rendered via note() — never enters LLM context |
| Context injection | `$(@ … @)` | standalone user message into the session — no inference |
| Bare sugar | `$prompt` | ≡ `$(prompt)` |
| Escape | `$$` | literal `$` |

**Extended delimiters**: `$(end# body containing #) literal #end)` —
opening `<delim>#`, closing `#<delim>)` strictly symmetric; a missing
closing falls back to a plain `$()` expression.

## Closing rules

- `${…}` closes on `}`, `$(…)` on `)` — bracket-balanced,
  string/comment aware
- Constructs may span lines inside triple-quoted strings; directives
  are always single-line

## Behavior rules

- **Line elimination**: if every construct on a line produces no
  output, the whole line is removed (directives, pure statements,
  comments, `$(@ @)` lines); note lines are **not** eliminated; blank
  lines kept
- **`text()` output**: `str` as-is; `None`→`null`; `bool`→`true/false`;
  dict/list/tuple→compact JSON; else `str(v)`
- **Reserved names** (binding → C300): `emit text submit save load
  new_ctx push_sink pop_sink note context`; function names `main
  prompt reply`; the `__pcl_` prefix

## Pass

```text
${:pass :read snapshot :write result}
```

- Prompt body runs to the next directive; auto-commit (trimmed)
- `:write` auto-wrap: sole authorized name + fully flat agent dict →
  nested
- Empty prompt skips; empty reply A504; unauthorized writes R406;
  write-back depth ≤ 32

## Error codes

| Class | Typical | Exit | Meaning |
|---|---|---|---|
| L | L100–L102 | 1 | lexical |
| P | P200–P203 | 1 | parse |
| C | C300/C305/C310 | 1 | compile constraints |
| R | R400/R406/R430 | 2 | runtime |
| A | A500–A523 | 3 | bridge |
| SIGINT | R409 | 130 | interrupt |

Common: **C305** comment not alone on its line; **C300** bound a
reserved name; **R406** agent wrote an unauthorized name; **A504**
agent produced no valid reply; **R430** `:load` session file missing.
