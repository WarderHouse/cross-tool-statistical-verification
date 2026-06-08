# MCP server

`crossverify` ships an [MCP](https://modelcontextprotocol.io/) server so an
**autonomous agent** can drive the verification directly: write a Python + R
analysis, call a tool, get back a **structured** pass/fail/info result, and
iterate — without parsing console text or shelling out to the CLI.

## Install and run

The server lives behind an optional extra (the MCP SDK needs Python ≥ 3.10):

```bash
pip install "crossverify[mcp]"
crossverify-mcp            # serves over stdio
```

Register it with an MCP client (stdio):

```json
{
  "mcpServers": {
    "crossverify": { "command": "crossverify-mcp" }
  }
}
```

## Tools

| Tool | Runs analysis code? | Returns |
|---|---|---|
| `verify_analysis(project_path, phases?, skip_r?, seed?)` | **yes** (sandboxed subprocess) | full result: `verdict`, `totals`, per-check `checks`, Python-vs-R `comparison`, `output_paths`, `scope_caveat` |
| `validate_project(project_path)` | no | `{ok, problems}` |
| `scaffold_project(target_dir)` | no | `{target, written, skipped}` |
| `inspect_dataset(csv_path)` | no | `{rows, columns, checks, artifacts}` |

Results are JSON the agent branches on — *which* checks failed and *why*, the
per-statistic `|Δ|` between Python and R — never a console summary to parse.

## Trust boundary

!!! warning "`verify_analysis` executes the analysis code the project points at"
    An agent that chooses `project_path` can cause arbitrary code execution.
    Two guardrails are enforced, but they are **not** a sandbox:

    1. **Path containment (default).** A project whose `data` / `python.module` /
       `r.script` resolve *outside* the project folder comes back
       `verdict="invalid"` — no code runs. Opt out per-project with
       `allow_external_paths: true` (only for projects you trust).
    2. **Bounded subprocess.** Each `verify_analysis` runs in a child process with
       a timeout (`CROSSVERIFY_MCP_TIMEOUT`, default 300 s) and a minimal,
       allowlisted environment, so a runaway or hostile analysis is time-bounded
       and cannot read the server's tokens or credentials.

    **Run the server in a sandbox** (container/VM, no credentials in the
    environment, least-privilege filesystem). The read-only tools do not execute
    analysis code.

Every `verify_analysis` result carries a `scope_caveat`: agreement across Python
and R is strong evidence a number is not a tool-specific artifact, but it is
**not** proof the analysis is correct (you write both sides, so a shared
specification error agrees perfectly). An agent must not report a verified
result as "correct" — see [The Protocol](PROTOCOL.md) for the full scope.

## The auto-researcher loop

A typical agent session:

1. **Scaffold.** `scaffold_project("study/")` writes `project.yaml`,
   `analysis.py`, and `analysis.R` to fill in.
2. **Write the analysis.** The agent writes the Python adapter (`run(df, seed)` →
   dict of statistics) and the independent R replication emitting the same names,
   and points `data:` at the dataset.
3. **Validate.** `validate_project("study/project.yaml")` → fix any `problems`
   before running code.
4. **Verify.** `verify_analysis("study/project.yaml")`. If `verdict == "fail"`,
   the result names the failing checks and the Python-vs-R deltas, e.g.:

    ```json
    {
      "verdict": "fail",
      "totals": {"passed": 9, "failed": 1, "info": 4},
      "comparison": [
        {"stat": "coef_x", "python": 1.8421, "r": 1.8407, "delta": 0.0014, "match": false}
      ]
    }
    ```

5. **Revise.** The agent reads that `coef_x` disagrees beyond tolerance, finds the
   cause (say an `na.rm`/`dropna` mismatch between the two implementations), fixes
   it, and calls `verify_analysis` again — looping until `verdict == "pass"`.

Because a failed check is a normal result (not an error) and the deltas are
machine-readable, the agent can close this loop on its own.
