#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PORT="${PORT:-8765}"
MAIN_TASK_ID="$(python -c "import json; print(json.load(open('demo/demo_manifest.json', encoding='utf-8'))['main_demo']['task_id'])")"
BACKUP_TASK_ID="$(python -c "import json; print(json.load(open('demo/demo_manifest.json', encoding='utf-8'))['backup_demo']['task_id'])")"

echo "Starting cs-mvp dashboard on http://127.0.0.1:${PORT}"
echo "Main demo:   http://127.0.0.1:${PORT}/runs/${MAIN_TASK_ID}"
echo "Backup demo: http://127.0.0.1:${PORT}/runs/${BACKUP_TASK_ID}"
echo

exec python -m cs_mvp.cli serve --host 127.0.0.1 --port "${PORT}"
