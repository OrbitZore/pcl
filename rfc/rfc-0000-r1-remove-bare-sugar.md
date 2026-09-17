---
Number: 0000-r1
Title: Remove the $prompt bare sugar
Status: Implemented
Type: Standards Track
Created: 2026-09-17
Implementation: pclang ≥ 0.2.0 (pre-release revision — no migration release)
Parent: rfc-0000-language
Language: English edition of rfc-0000-r1-remove-bare-sugar.zh.md
---

# RFC 0000-r1 — Remove the `$prompt` bare sugar

## Summary

The `$prompt` bare sugar (formerly ≡ `$(prompt)`) is removed. Prompt
injection in templates is always written `$(prompt)`; a literal
`$prompt` in source is a compile error — **L103** — with migration
guidance.

## Motivation

1. **An unjustified special case**: only `prompt` ever had sugar while
   every other variable needed `$(name)` — asymmetric, extra learning
   cost
2. **Hidden semantics**: `$prompt` reads like a shell variable,
   suggesting a general `$name` syntax that does not exist
3. **Cheap to remove now**: nothing has been released (0.2.0.dev0,
   code-only state) — no external templates depend on it; dropping it
   before alpha avoids a permanent compatibility burden

## Specification

1. Lexical layer: `$` + a full identifier exactly `prompt` no longer
   expands to a merged interpolation; it is now a compile error:

   ```
   t.pcl:1:4 [L103] 裸糖 $prompt 已移除：请改用 $(prompt)
   ```

2. Longest-identifier matching is preserved: `$prompts`, `$promptX`,
   `$prompté` etc. are not `prompt` and remain plain text; `$$prompt`
   goes through escaping first and emits a literal `$prompt`
3. `$(prompt)` / `${prompt}` semantics are unchanged
4. RFC 0000's construct table drops the bare-sugar row; the lexical
   error family widens to L100–L103

## Drawbacks

- Two characters become six; templates are slightly longer
- Old draft templates (unreleased) need a mechanical
  `$prompt` → `$(prompt)` replacement

## Alternatives

- **Keep the sugar and document it**: rejected — an asymmetric special
  case becomes nearly impossible to reclaim once released
- **Generalize `$name` as universal sugar**: rejected — its
  interactions with `$$` escaping and the `$(`/`${` forms would
  complicate the lexer significantly, and it invites implicit-template-
  variable abuse

## References

- [RFC 0000](rfc-0000-language.md) (the parent spec of this revision)
