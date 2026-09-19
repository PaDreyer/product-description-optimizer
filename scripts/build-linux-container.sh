#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
image_name="pdo-linux-builder:bookworm"

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "The Linux release image currently supports x86_64 only." >&2
  exit 1
fi

docker build \
  --file "$project_root/packaging/linux/Dockerfile" \
  --tag "$image_name" \
  "$project_root"

docker run --rm \
  --user "$(id -u):$(id -g)" \
  --env HOME=/tmp \
  --volume "$project_root:/workspace" \
  "$image_name"
