#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dev_venv="$project_root/venv"

if [[ "$#" -ne 0 ]]; then
  echo "Usage: $0" >&2
  exit 2
fi

python3 -m venv "$dev_venv"
"$dev_venv/bin/python" -m pip install --upgrade pip
"$dev_venv/bin/python" -m pip install -e "$project_root[dev,desktop,gemini,zhipuai,openai]"

echo "Development environment is ready."
echo "Activate it with: source venv/bin/activate"
