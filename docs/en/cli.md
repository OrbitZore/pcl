# CLI Manual

Command `pcl` (distribution `pclang`); `python -m pcl` equivalent.

## pcl run

```bash
pcl run <file.pcl> [PROMPT…] [options]
```

| Option | Description |
|---|---|
| `--agent NAME` | `pi` (default, real agent) / `null` (reply=prompt, debugging) / `script` (JSONL replay) |
| `-o FILE` | write the output document to FILE (default stdout) |
| `--trace` | streaming stderr diagnostics: pass submissions, thinking deltas, pcl_write, turn boundaries |
| `--cache none\|dir` | cache policy (default per settings) |
| `--pi-bin PATH` / `--pi-arg ARG` | pi executable & pass-through args (repeatable) |
| `--script-path FILE` | script-bridge replay file |
| `--timeout SEC` | per-pass timeout |

Positional arguments become the template's `prompt` variable
(space-joined).

### Shebang execution

First line `#!/usr/bin/env pcl` + `chmod +x`:

```bash
./goal.pcl "task description"
```

## pcl gen / pcl check

```bash
pcl gen file.pcl        # print generated Python (with # pcl:N annotations)
pcl check file.pcl      # compile-only check
```

The first tool for "what code did my template generate".

## pcl config

```bash
pcl config              # effective config + per-key source (CLI/project/user/built-in)
pcl config --defaults
```

## pcl version

Version + protocol handshake info (runtime & target connector paths).

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | compile-time error (L/P/C) |
| 2 | runtime error (R) |
| 3 | bridge error (A) |
| 130 | user interrupt (Ctrl-C) |

## Cache

- Location: `$XDG_CACHE_HOME/pcl` (default `~/.cache/pcl`)
- Named `<stem>-<sha8>.pcl.py`; atomic writes; 2 most recent per stem
- Editing the template auto-recompiles (content-hash miss)

## Debugging tips

```bash
pcl gen file.pcl | less          # inspect generated code
pcl run --agent null file.pcl    # template logic without an agent
pcl run --trace file.pcl 2>trace.log   # full trace
```
