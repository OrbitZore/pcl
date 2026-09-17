# Guide

Concepts and patterns for users. Normative definitions:
[RFC 0000](https://github.com/OrbitZore/pcl/blob/main/rfc/rfc-0000-language.md).

## The two-layer model

- **Template layer**: text + `${…}` constructs — a "prompt template
  with control flow"
- **Script layer**: real Python inside `${…}`/`$(…)` — expressions,
  assignments, imports, stdlib, third-party libraries, all native

A program's product = output document (stdout or `-o` file) + side
effects (agent interaction, context switches).

## Interpolation dual forms

| Form | Flush | Use |
|---|---|---|
| `${expr}` | Construct is a flush point; standalone emit, **1:1 line numbers** | The default; side effects stay ordered |
| `$(expr)` | Never flushes; woven into the merged segment | Splicing several values on one line |

Rule of thumb: **default to `${}`**; use `$()` when splicing multiple
values on one line or controlling blank lines precisely. Pure
statements (assignments/imports) execute silently in both; prefix
side-effecting calls with `_ =`.

```text
${import json}
${items = ["a", "b"]}
${len(items)} items: $(json.dumps(items))     ← both forms on one line
```

## Pass: one agent interaction

```text
${:pass :read MY_VAR :write RESULT}
<prompt body — any mix of text and interpolation>
```

Lifecycle:

1. **Render**: the prompt body renders into an isolated buffer (never
   the output document)
2. **Commit**: auto-commits at the next directive or EOF (trimmed)
3. **Wait**: the agent finishes the turn; meanwhile it may read the
   snapshot via `pcl_read` and write via `pcl_write`
4. **Write-back**: `:write`-declared variables get assigned; the reply
   goes to the output document and the variable `reply`

Key points:

- `:read X` — freezes a snapshot of X at pass start for the agent
- `:write X` — the **sole authorized name**. A flat dict from the
  agent (`{"done": true}` instead of `{"X": {...}}`) is auto-wrapped;
  mixing authorized + unauthorized names → R406
- An empty prompt skips the bridge entirely
- `${}` inside a pass body executes **before** the commit — to process
  the result, place statements **outside the pass body, past the next
  directive** (below)

### Post-writeback processing: the directive boundary

A pass body ends at the **next directive**. Written values exist only
after the commit, so post-processing must sit after a directive:

```text
${:pass :write W}
Executor: … write {"W": "action summary"}

${:new}
${HISTORY = HISTORY + (W if isinstance(W, str) else str(W)) + "\n"}  ← after :new = past the directive boundary; W is Pass 1's write-back
${:pass :write W}
Inspector: actions so far: $(HISTORY)… write {"W": {"done": true/false}}
${:if isinstance(W, dict) and W.get("done")}    ← :if condition evaluates after writeback
    ${:break}
${:fi}
```

Two correct places to read a written value: **pure statements after
the next directive** (e.g. between Pass 2's `${:new}` and `${:pass}`
— placing them inside the previous pass body is a common error and
reads the stale pre-commit value), or **a directive's
condition expression** (evaluated post-writeback).

## Context management: :new / :save / :load

| Directive | Effect |
|---|---|
| `${:new}` | Fresh session — **all history cleared** (the agent sees nothing prior) |
| `${:save name}` | Persist the session; `name` = opaque token |
| `${:load name}` | Switch back to the saved session |

- After `:new`, pass prompts **must be self-contained** (goal,
  history, round number spelled out)
- Token persistence across runs is your business:
  `${open("ctx.txt","w").write(TOKEN)}`

## Pattern: the goal loop

Act + check per round, stop when done (full runnable version:
[examples/goal-loop.pcl](https://github.com/OrbitZore/pcl/blob/main/examples/goal-loop.pcl)):

```text
${:while ROUND < MAX}
    ${ROUND = ROUND + 1}
    ${:new}
    ${:pass :write W}        ← Pass 1: act (self-contained prompt)
    ${HISTORY = HISTORY + W + "\n"}   ← after a directive: reads Pass 1's write-back
    ${:new}
    ${:pass :write W}        ← Pass 2: check
    ${:if isinstance(W, dict) and W.get("done")}
        ${DONE = True}
        ${:break}
    ${:fi}
${:done}
```

## Notes and context injection

| Construct | Destination | Typical use |
|---|---|---|
| `$(# … #)` note | standalone → output doc; embedded → in-session entry (**never enters LLM context**) | round progress, final verdicts |
| `$(@ … @)` context injection | standalone user message into the agent session (**no inference triggered**) | goal declarations, background material |

Both are full template bodies — `${}`/`$()`/directives work inside.
When the body contains a literal delimiter, use the extended form:
`$(end# … #end)`, `$(tag@ … @tag)`.

## Directive cheat sheet

| Directive | Effect |
|---|---|
| `${:if}`/`${:elif}`/`${:else}`/`${:fi}` | conditionals |
| `${:while …}${:done}` / `${:for X in …}${:done}` | loops |
| `${:break}` / `${:continue}` | loop control |
| `${:function f(x)}…${:endfunction}` / `${:return}` | functions |
| `${:pass [:read X] [:write Y]}` | agent interaction |
| `${:save T}` / `${:load T}` / `${:new}` | context |
| `${:# comment}` / `${# comment}` | comments (own line only) |

## Two pi integrations

**Forward (terminal)** — `pcl run --agent pi file.pcl`: PCL spawns a
headless `pi --mode rpc` in its own session, runs to completion,
exits. Good for scripting / CI / one-shot tasks.

**Embedded (inside a pi session)** — in the pi conversation you're
already using:

```text
/pcl run /path/to/goal.pcl "task description"
```

- Passes go straight into **your current session** — the agent sees
  your conversation context
- Output goes to a temp file; `$(# … #)` notes appear as session
  entries that scroll with the chat (never entering LLM context)
- `:new`/`:load` inside the script switch the session you're looking
  at (guarded by takeover rules, see
  [RFC 0002 §7](https://github.com/OrbitZore/pcl/blob/main/rfc/rfc-0002-connector.md))
- Other subcommands: `/pcl gen|check|config|version` mirror the CLI

**`~/.pcl/bin/` quick commands** — drop executable `.pcl` scripts
into that directory; the connector scans recursively and registers
them as slash commands: paths flatten into command names
(`tools/review` → `/pcl-tools-review`), **always embedded in the
current session** (never spawned):

```bash
mkdir -p ~/.pcl/bin
cp examples/goal-loop.pcl ~/.pcl/bin/goal.pcl
chmod +x ~/.pcl/bin/goal.pcl
# restart pi, then:
/pcl-goal "Create hello.txt with content Hello PCL"
```

> Scripts in `~/.pcl/bin/` execute inside your session — only place
> templates from sources you trust (equivalent to handing an arbitrary
> prompt to the agent; see SECURITY.md).
