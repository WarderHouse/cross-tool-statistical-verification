# Confidentiality

`cross-tool-statistical-verification` is built to be safe to run on **unpublished data and
unpublished results**.

## What leaves your computer

Nothing.

The harness reads your dataset and your analysis scripts from local disk, runs
Python (and, for Phase 5, a local R process), and writes its outputs back to
local disk. It opens no network connections, uses no API, contacts no AI or LLM
service, and emits no telemetry or analytics.

| Action | Destination |
|---|---|
| Read dataset | local disk |
| Run Python adapter | local Python process |
| Run R replication | local `Rscript` process |
| Write log, tables, methodology statement | local disk (`crossverify_out/`) |
| Network / cloud / AI / telemetry | **none** |

You can confirm this by running it offline.

## What stays out of version control

This repository's [.gitignore](.gitignore) excludes:

- `crossverify_out/` — all generated verification logs, tables, and JSON
- `projects/` — a directory for your real studies

Put your actual analyses under `projects/` (or anywhere outside the repo) and
your data, code, and results will never be committed, even though this
repository is public. The only project tracked in git is the public-domain
`examples/` demonstration.

## One line for collaborators or IT

> It runs entirely locally, makes no network calls, sends nothing to any AI
> service, and keeps your data and results out of version control by default.
