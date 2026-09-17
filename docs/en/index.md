# PCL — Prompt Control Language

A template language for orchestrating LLM agents: **the template layer
is PCL, the script layer is real Python**.

## Why PCL?

- **Zero lock-in**: your logic is plain Python — import any library,
  use any tool
- **Readable & debuggable**: `.pcl` compiles to readable Python source
  with line annotations (`# pcl:N`); tracebacks point back at your
  template
- **Full agent control**: structured write-back, session context
  management, multi-round loops — all first-class language constructs
- **Zero dependencies**: pure Python ≥3.10, nothing installed at runtime

## One-minute example

```text
${ROUND = 0}
${DONE = False}
${W = ""}
${MAX = 100}

${:while ROUND < MAX}
    ${ROUND = ROUND + 1}

    ${:new}
    ${:pass :write W}
    Executor (round $(ROUND)/$(MAX)). Fresh context — everything you
    need is below.
    Task goal: $prompt
    Call pcl_write exactly once with: {"W": "one-line action summary"}

    ${:new}
    ${:pass :write W}
    Inspector (round $(ROUND)/$(MAX)). Fresh context — judge from the
    evidence below.
    Task goal: $prompt
    Call pcl_write exactly once with:
    {"W": {"done": true/false, "note": "one-line verdict"}}

    ${:if isinstance(W, dict) and W.get("done")}
        ${DONE = True}
        ${:break}
    ${:fi}
${:done}

${:if DONE}
$(# 🎉 Goal achieved in round $(ROUND)/$(MAX)#)
${:fi}
```

```bash
pcl run goal.pcl "Create hello.txt with content Hello PCL"
```

## Start here

- **[Quickstart](quickstart.md)** — install, first template, 5 minutes
- **[Guide](guide.md)** — passes, write-back, context, loop patterns
- **[Language Reference](language.md)** — cheat sheet & semantics
- **[CLI Manual](cli.md)** — run/gen/check/config & exit codes
- **[Settings](settings.md)** — user/project configuration
- **[Examples](examples.md)** — runnable examples tour
- **[FAQ](faq.md)** — common questions

## Ecosystem

- First agent adapter: [pi](https://github.com/earendil-works/pi-coding-agent)
  (forward CLI + in-session `/pcl` embedded mode)
- Normative specs: [RFC directory](https://github.com/OrbitZore/pcl/tree/main/rfc)
- Contributing: [CONTRIBUTING](https://github.com/OrbitZore/pcl/blob/main/CONTRIBUTING.md)

## License

[GPL-3.0](https://github.com/OrbitZore/pcl/blob/main/LICENSE)
