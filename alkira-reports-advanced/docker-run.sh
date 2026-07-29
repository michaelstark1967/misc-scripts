#!/usr/bin/env bash
set -euo pipefail

# Runs the alkira-aggregate container with sensible defaults for RHEL hosts.
# Usage: ./docker-run.sh [--image name[:tag]] [--env-file path] [--command "cmd args"]

IMAGE_NAME="alkira-aggregate:1.2.1"
ENV_FILE=".env"
CMD=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --image) IMAGE_NAME="$2"; shift 2;;
    --env-file) ENV_FILE="$2"; shift 2;;
    --command) CMD="$2"; shift 2;;
    *) echo "Unknown arg: $1"; exit 1;;
  esac
done

if [[ ! -f "$ENV_FILE" ]]; then
  echo "env file '$ENV_FILE' not found. Copy .env.example to .env and set values." >&2
  exit 1
fi

# Use podman on RHEL if available, otherwise docker
if command -v podman >/dev/null 2>&1; then
  RUNTIME=podman
else
  RUNTIME=docker
fi

if [[ -z "$CMD" ]]; then
  # Default: run the wrapper (the image ENTRYPOINT will also run it)
  ${RUNTIME} run --rm --env-file "$ENV_FILE" -v "$PWD":/app "$IMAGE_NAME"
else
  ${RUNTIME} run --rm --env-file "$ENV_FILE" -v "$PWD":/app "$IMAGE_NAME" sh -c "$CMD"
fi
