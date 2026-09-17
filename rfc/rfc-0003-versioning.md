---
Number: 0003
Title: Versioning Plan
Status: Accepted
Type: Process
Created: 2026-09-17
Implementation: none (first release pending)
Language: English edition of rfc-0003-versioning.zh.md
---

# RFC 0003 — Versioning Plan

## Summary

Defines PCL's version naming, release sequence, stage exit criteria,
and stability-tier promises. PEP 440 format + semver semantics; the
release sequence **starts from alpha**; `1.0.0` freezes the language
spec.

## Motivation

The project is about to publish its first release (PyPI `pclang` +
npm `pcl-connector-pi`). Without an explicit version policy, users
cannot tell what changes and what doesn't, contributors cannot tell
which version a change targets, and multi-backend connectors cannot
align protocol versions. Rationale for starting at alpha: the feature
set is complete but not yet validated by external users at scale —
going stable too early turns every bugfix into a breaking change.

## Specification

### 1. Naming rules

- **PEP 440** format + **semver** semantics; tags prefixed `v`
  (`v0.2.0a1`)
- Version **single source**: `pclang/src/pcl/_version.py` (pyproject
  reads it dynamically; `pcl-connector/pi/package.json` is guarded
  consistent by the CI consistency job)
- PyPI (`pclang`) and npm (`pcl-connector-pi`) **publish the same
  semantic version in lockstep**; pre-release separators follow each
  ecosystem's convention: PEP 440 `0.2.0a1` ↔ npm semver `0.2.0-a1`
  (CI consistency compares normalized)

### 2. Release sequence

```
now           0.2.0.dev0 (code-only state, never released — skipped)
────────────────────────────────────────────────────
Alpha   0.2.0a1 → a2 → a3 …      first release = everything built so far
Beta    0.2.0b1 → b2 …           feature freeze; bugfix/docs only
RC      0.2.0rc1 → rc2 …         critical fixes only; protocol handshake frozen
Stable  0.2.0                    first stable release
────────────────────────────────────────────────────
Minor   0.3.0 / 0.4.0 …          new features (each may pre-release aN)
1.0.0                           language spec frozen
```

- **`0.2.0a1` (first release) contents**: M0–M4 (compiler/runtime/
  bridge/embedded mode), the settings system, `~/.pcl/bin/` embedded
  commands, the examples suite, the RFC corpus, bilingual docs
- **Later minor candidate directions** (each goes through a new RFC —
  not promises):
  - `0.3.0`: language enhancements (multiple `:write` variables,
    parameterized passes, note-subtemplate line-number offset mapping)
  - `0.4.0`: new agent-backend subpackages (`claude-code/`,
    `gemini-cli/`, per the RFC 0002 contract)
  - `0.5.0`: import ecosystem / caching / performance
- **During `0.x`**: minors may break — flagged prominently in
  CHANGELOG + an RFC revision

### 3. Stage exit criteria

| Stage | Entry | Exit |
|---|---|---|
| Alpha | first release | README syntax surface unchanged ≥30 days; alpha issues converge |
| Beta | the above | no open P0/P1 issues |
| RC | Beta satisfied | zero critical regressions during rc |
| 0.2.0 | — | — |
| **1.0.0** | RFC 0000/0001/0002 all `Final` + ≥2 stable minor cycles + connector protocol v1 frozen | strict semver afterwards (only majors break) |

### 4. Stability-tier promises

| Tier | Stable from | Notes |
|---|---|---|
| README syntax surface | **alpha onward** | the minimal user-visible stable surface |
| CLI subcommands/exit codes/error-code families | **alpha onward** | debug scripts & CI depend on them |
| RFC 0000 language (full) | **0.2.0** (frozen at beta) | spec-level promise |
| RFC 0001/0002 (runtime/connector protocol) | **0.2.0** | multi-backend alignment; handshake via `pcl version` |
| Settings schema | adding keys anytime; removing/renaming → minor + RFC | |

### 5. Release checklist

1. Bump `_version.py` (single source; CI guards package.json parity)
2. CHANGELOG: `Unreleased` → version + date; footer links completed
3. `git tag vX.Y.ZN && git push --tags`
4. `cd pclang && uv build && uv publish`
5. Connector `npm publish` (same version); verify the `pcl version`
   handshake

## Alternatives

- **Ship 0.2.0 stable directly**: rejected — complete features but no
  external-user validation; every bugfix would become a breaking change
- **Start at 0.1.0**: version history (git/CHANGELOG) is already on
  the 0.2 line; rolling back is meaningless
- **Long-lived pre-releases (`0.2.0.dev0` on PyPI)**: the `dev`
  suffix is the weakest signal for dependency resolvers and users
  install it by mistake; the alpha/beta/rc progression is clearer

## Unresolved Questions

(none)

## References

- [PEP 440](https://peps.python.org/pep-0440/), [semver](https://semver.org/)
- RFC 0000/0001/0002 (the specs the stability promises attach to)
- [CONTRIBUTING.md](../CONTRIBUTING.md) (contributor-facing summary)
