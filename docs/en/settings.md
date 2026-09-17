# Settings

For users. Full rules (trust model, merge algorithm):
[RFC 0001 §8](https://github.com/OrbitZore/pcl/blob/main/rfc/rfc-0001-runtime.md).

## Two layers

| Layer | Path | Purpose |
|---|---|---|
| User | `~/.config/pcl/settings.json` (or `$PCL_CONFIG_FILE`) | your environment |
| Project | nearest `.pcl/settings.json` walking up from the entry `.pcl` | shipped with a repo |

Precedence: **CLI > project > user > built-in defaults**. Format is
JSONC (`//` comments and trailing commas allowed).

## Common configuration

```jsonc
{
  // bridge: pi / null / script
  "agent": "pi",
  // per-pass timeout (seconds)
  "timeout": 900,
  // default --trace
  "trace": false,
  "cache": {
    "disable": false,       // true = recompile every time
    "dir": null,            // custom cache dir (relative to the settings file)
    "keep_per_stem": 2
  }
}
```

**User-level only** (an error if present at project level):

```jsonc
{
  "pi": {
    "bin": "/usr/local/bin/pi",
    "connector_path": "~/pi/pcl-connector/pi",
    "args": ["--model", "glm-5.3"]   // concatenated across layers
  },
  "script": { "path": "replay.jsonl" }
}
```

> Why the restriction? A project file is untrusted input you get by
> cloning — letting it name executables/extensions would let a repo
> silently run arbitrary code. Behavioral knobs (agent/timeout/trace/
> cache) are project-safe; executable surfaces (pi.bin etc.) are not.

## Inspecting effective config

```bash
pcl config            # per-key values + source (CLI/project/user/built-in)
pcl config --defaults
```

## Environment variables

| Variable | Effect |
|---|---|
| `PCL_CONFIG_FILE` | redirect the user-level file |
| `PCL_NO_PROJECT_CONFIG` | ignore project settings (sealed run) |
| `PCL_BIN` | used by the connector to spawn pcl in embedded mode |
