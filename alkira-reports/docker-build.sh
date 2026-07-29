#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

IMAGE_NAME="alkira-aggregate:1.2"

echo "Building Docker image $IMAGE_NAME..."
docker build -t "$IMAGE_NAME" .

echo "Build complete. To run:"
echo "  docker run --rm --env-file .env -v \"$PWD\":/app $IMAGE_NAME"

echo "Or with podman:"
echo "  podman build -t $IMAGE_NAME ."
echo "  podman run --rm --env-file .env -v \"$PWD\":/app $IMAGE_NAME"
