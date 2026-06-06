# crossverify

**Check a statistical analysis the way a careful reviewer would:** confirm the
numbers are internally consistent, reproduce identically on a second run, and
**agree with an independent implementation in another tool**. `crossverify` runs
your analysis through a documented six-phase protocol and writes the evidence — a
verification log, a Python-vs-R comparison table, and a methodology statement you
can adapt for a manuscript.

It establishes that a result is **implementation-independent**, not that it is
*correct*: agreement across Python and R is strong evidence a number is not an
artifact of one library's defaults, but you write both sides, so a shared
specification error agrees perfectly. See
[The Protocol](PROTOCOL.md) for the scope and limits.

## Where to go next

- **[The Protocol](PROTOCOL.md)** — what each of the six phases does, in brief and
  in technical detail. The conceptual centerpiece; start here.
- **[API Reference](reference/cli.md)** — the public modules, generated from the
  source docstrings.

## Quickstart

`crossverify` uses [uv](https://docs.astral.sh/uv/) and runs entirely on your
machine (no network, no telemetry):

```bash
uv sync
uv run crossverify --project examples/project.yaml
```

```
crossverify 0.1.1 — OLS regression: mpg ~ wt + hp (mtcars)
  Phase 5 triangulation    11 pass
  Cross-tool: 11/11 statistics matched within tolerance.

Result: PASS (30 passed, 0 failed, 4 informational)
```

The cross-tool phase additionally needs **R** with the `jsonlite` package; use
`--skip-r` to run the Python-only phases. Full install and usage details are in
the [README](https://github.com/WarderHouse/cross-tool-statistical-verification#readme).
