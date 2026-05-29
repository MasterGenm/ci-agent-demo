# Demo Case Package

This directory is the v1.2 evaluator demo package for `cs-mvp`.

It intentionally contains one main demo and one backup demo only. The goal is to keep the evaluation flow stable and readable instead of turning the demo into a four-case benchmark suite.

## Contents

| File | Purpose |
| --- | --- |
| `demo_manifest.json` | Fixed metadata for the main and backup demo runs. |
| `main_case.json` | Re-runnable input template for the v1.2 full-path demo. |
| `backup_case.json` | Re-runnable input template for the legacy case 4 comparison. |
| `run_demo.sh` | Linux/macOS helper to start the dashboard and print demo URLs. |
| `run_demo.ps1` | Windows PowerShell helper to start the dashboard and print demo URLs. |

## Main Demo

Task ID:

```text
T-v12-b2-smoke-rescue-on
```

Use this run for the five-minute evaluation walkthrough:

1. Open the DAG tab and point out the seven-node flow.
2. Open the QA Critic tab and show accepted versus needs_revision audit results.
3. Open the Report tab and show that the report is evidence-linked.
4. Open the Evidence tab when a reviewer asks how a conclusion is sourced.
5. Open the Trace tab only if the reviewer asks about observability, cost, or intermediate state.

This run includes `qa_audit.json`, `qa_summary.md`, `rescue_outcomes.json`, `review_queue.json`, `trace.json`, and the normal report/evidence artifacts.

## Backup Demo

Task ID:

```text
T-50d7bb2f823e444994deac9cc85f0e8e
```

Use this run only when the main run is not available or when you want to show v1.1 artifact compatibility. It is a real case 4 legacy run, so the QA Critic tab is expected to show that QA was not enabled.

## Start Dashboard

Windows:

```powershell
.\demo\run_demo.ps1
```

Linux/macOS:

```bash
./demo/run_demo.sh
```

Manual command:

```bash
python -m cs_mvp.cli serve --host 127.0.0.1 --port 8765
```

Then open:

```text
http://127.0.0.1:8765/runs/T-v12-b2-smoke-rescue-on
http://127.0.0.1:8765/runs/T-50d7bb2f823e444994deac9cc85f0e8e
```

## Rerun From Templates

The two JSON files are input templates for future reruns. They do not force the existing task IDs. If a rerun is needed, use their `query`, `competitors_cli`, `seed_urls`, and feature flags as the source of truth, then record the new task ID in `demo_manifest.json` after review.

Do not store API keys or `.env` files under `demo/`.
