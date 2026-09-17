---
Number: 0002
Title: PCL Connector Definition
Status: Implemented
Type: Standards Track
Created: 2026-09-17
Implementation: pcl-connector/pi ≥ 0.2.0
Language: English edition of rfc-0002-connector.zh.md
---

# RFC 0002 — Connector Definition

## Summary

Defines the agent-side connector contract: a connector is an extension
inside the host agent (first: pi) implementing the `/pcl` command
family, the `pcl_write`/`pcl_read` tools, the RPC proxy table, and
session-takeover rules — plus the **interface between the connector
and the runtime (RFC 0001)**. Multi-backend by design: one
subdirectory per host agent (`pcl-connector/<backend>/`).

## Motivation

The runtime (Python) understands no agent — all interaction flows
through the bridge protocol. The connector is the agent-side endpoint
of that protocol: translating PCL pass signaling into host-session
operations and host tools into PCL write-backs. An explicit contract
keeps backends swappable, protocol versions negotiable, and the two
modes (embedded/forward) consistent.

## Specification

### 1. Two modes

| Mode | Launch | Transport | Session |
|---|---|---|---|
| **forward** | `pcl run --agent pi` spawns `pi --mode rpc -e <connector>` | child stdio JSONL (PCL side reads the fd via select+os.read — never touches the BufferedReader lock) | owned by PCL |
| **embed** | user runs `/pcl run <file.pcl>` inside a pi session | the runtime child (`pcl run --agent embed -o <tmp>`) talks over its own stdio to the host connector | **the user's current session** |

### 2. `/pcl` command family

| Subcommand | Semantics |
|---|---|
| `run <file.pcl> [PROMPT…] [options…]` | embedded execution: waitForIdle → spawn `pcl run … --agent embed -o <tmp>` and proxy the protocol |
| `gen`/`check`/`config`/`version` | pure CLI passthrough (spawn, capture stdout) |
| `pass` (machine subcommand, never in completions) | the sole per-pass signal: `/pcl pass {payload}`; payload always has all three keys (§5) |

The connector is the **single registered command entry** — only `/pcl`
appears in the human command palette.

### 3. Tools

| Tool | Contract |
|---|---|
| `pcl_write` | Argument `{"values": {name: JSON value}}` (named key `values` — the host validation layer strips top-level open shapes); **deny-first**: unauthorized names rejected at the tool layer so the agent retries in-turn; empty values rejected |
| `pcl_read` | Reads the variable snapshot frozen at pass start (answered locally, no LLM turn); unknown names rejected with the readable list |

### 4. Protocol injection

`before_agent_start` (host event): only when the current pass declares
read/write names, append pcl_write/pcl_read usage to this turn's
system prompt (chained; never persisted into the session).

### 5. Pass signaling

- Payload: `{"writable": [...], "reads": {...}, "text": "..."}` —
  **all three keys always present** (even when empty)
- Delivery: the connector registers the whitelist/snapshot, then
  `pi.sendUserMessage(text)` into the current session (no expansion
  by default; a `/`-leading pass text is immune to subcommand parsing)
- **`agent_settled` is the sole pass boundary**: sendUserMessage is
  fire-and-forget (its response arrives at preflight, not completion)
- Write-back collection: `pcl_write` calls in the tool-execution event
  stream, merged by name

### 6. RPC proxy table

In embedded mode the runtime reaches the host through the connector:

| Command | Use |
|---|---|
| `prompt` / `get_state` / `get_commands` | readiness probe, state |
| `get_last_assistant_text` | reply extraction (A502 tolerated, falls back to cache) |
| `note` | note → `appendEntry("pcl-note")` custom session entry (never enters LLM context) |
| `context` | context injection → `sendMessage(triggerTurn=false)` (enters context, no inference) |
| `abort` | abort the current turn |
| `set_session_name` / `new_session` / `switch_session` | the three context directives mapped (§7, §8) |

### 7. Session continuation (embedded mode)

`:new`/`:load` replace **the host session**:

- **Binding levels**: L1 (event context) → L2 (command context, may
  perform session operations); any `/pcl` subcommand upgrades back to
  L2 with the current command ctx
- **Takeover rules** (session_shutdown):
  - quit → close stdin first (the runtime reads EOF and finishes cleanly)
  - reload → broken pipe; the bridge is orphaned
  - **new/resume/fork not initiated by the bridge** → wait for a new
    instance to take over (auto-follow, 10 s window; expiry → in-flight
    commands fail with A52x embed-orphaned)
- A context operation on an L1 binding after auto-follow → **A523**
  (guidance: run any /pcl command to restore, or switch to forward CLI)
- `switch_session` **cross-cwd rejected** (embed-cross-cwd): the module
  must reload and the bridge orphans — guide to the forward CLI
- `set_session_name`: the runtime never sends it in embed mode (never
  renames the host session); in forward mode save() opportunistically
  renames to `pcl:<stem>` for /resume discoverability

### 8. `~/.pcl/bin/` auto commands

- Recursively scan executable files; flattened paths register as
  `/pcl-<dir>-<name>`
- **Always treated as pcl scripts via the `/pcl run` path, embedded in
  the current session** (never spawned directly)
- Arguments pass through as `run` positional args

### 9. Multi-backend extension

- Layout: `pcl-connector/<backend>/` (first: `pi/`)
- Each backend implements the equivalents of §2–§8 (command family /
  tools / proxy table / takeover rules may be trimmed to host
  capabilities, but the three-key pass signaling and the settled
  boundary are non-negotiable)
- Error codes A520–A523 are reserved for embedded orphan/degradation
  scenarios

## Connector ↔ Runtime Interface

The wire protocol between the runtime (RFC 0001 `IAgentBridge`) and
the connector:

| Direction | Frame | Semantics |
|---|---|---|
| runtime → connector | `{"type": "/pcl pass", three-key payload}` | submit a pass |
| connector → runtime | tool-execution event stream (pcl_write/pcl_read calls & results) | write-back channel |
| connector → runtime | `agent_settled` | the (sole) pass boundary |
| runtime → connector | §6 proxy-table RPC | session/context operations |
| connector → runtime | RPC response (success/cancelled/reason) | outcome (A50x/A52x attribution) |

Handshake: `pcl version` prints the runtime version + target connector
path (R16 diagnostics).

## Conformance

A connector must: keep all three payload keys present, treat settled
as the sole boundary, deny-first on the write list, align the embedded
proxy semantics (cancelled→A501, cross-cwd rejection, L1 degradation
A523), and always run `~/.pcl/bin/` commands embedded.

## References

- RFC 0000 — Language Definition (pass/context directive semantics)
- RFC 0001 — Runtime Definition (IAgentBridge, submit protocol)
