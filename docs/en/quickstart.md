# Quickstart

Five minutes: install → first template → watch the agent write back
a variable.

## Install

```bash
pip install pclang        # PEP 668 systems (Arch/conda…): uv tool install pclang / pipx install pclang
```

Python ≥ 3.10. `pclang` is the distribution name; the command and
import name is `pcl`.

## First template (no agent)

Create `hello.pcl`:

```text
${NAME = prompt or "world"}

Hello, $(NAME)!
Today is ${import datetime; datetime.date.today().isoformat()}.
```

Run:

```bash
pcl run hello.pcl "PCL"
```

Output:

```text
Hello, PCL!
Today is 2026-09-17.
```

You just used PCL's core ideas:

- `${…}` holds **real Python statements** (assignments, imports, anything)
- `$(…)` weaves an expression's value **into the text**
- `$(prompt)` is the first positional argument (`pcl run x.pcl "task"` → `prompt = "task"`)

## Add an agent: one pass

Prerequisite: [pi](https://github.com/earendil-works/pi-coding-agent)
installed with a model configured. Create `score.pcl`:

```text
${SCORE = 0}

${:pass :write SCORE}
Write one sentence about the topic, then call pcl_write with your
self-rated quality score (0-10 integer) written to SCORE:
$(prompt)

${:if SCORE >= 7}
✔ Quality passed ($(SCORE))
${:else}
✘ Score too low ($(SCORE))
${:fi}
```

Run:

```bash
pcl run score.pcl "Why is the sky blue"
```

What happened:

1. `${:pass :write SCORE}` sends the text below to the agent (pi)
2. The agent calls the `pcl_write` tool to write `SCORE`
3. PCL continues with the written value — `${:if SCORE >= 7}` is just
   a Python conditional

**Debugging without an agent**:

```bash
pcl run --agent null score.pcl "test"   # reply = prompt verbatim
```

## Shebang execution

```bash
echo '#!/usr/bin/env pcl' | cat - score.pcl > score2.pcl
chmod +x score2.pcl
./score2.pcl "Why is grass green"
```

## Running inside a pi session

With the connector installed (`pi install npm:pcl-connector-pi`), you
never leave the conversation:

```text
/pcl run ./score.pcl "Why is the sky blue"
```

**`~/.pcl/bin/` quick commands** — executable `.pcl` files dropped
there become slash commands automatically:

```bash
mkdir -p ~/.pcl/bin && cp score.pcl ~/.pcl/bin/
chmod +x ~/.pcl/bin/score.pcl
# after restarting pi: /pcl-score "Why is the sky blue"
```

See [Guide · two pi integrations](guide.md#Two-pi-integrations).

## Next

- [Guide](guide.md) — pass lifecycle, `:new`/`:save`/`:load`, the goal
  loop, notes and context injection
- [Language Reference](language.md) — full construct cheat sheet
- Errors? [FAQ](faq.md) has an error-code quick table
