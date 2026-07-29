#!/usr/bin/env bash
# Build and run the cron-enabled container for daily Alkira reports.
# Usage: ./docker-run-cron.sh [--image-name name] [--env-file /path/to/.env] [--cron-schedule "m h dom mon dow"]

set -euo pipefail

IMAGE_NAME="alkira-aggregate-cron:1.0"
ENV_FILE=""
CRON_SCHEDULE=""
DETACH=true

while [[ $# -gt 0 ]]; do
  case $1 in
    --image-name) IMAGE_NAME="$2"; shift 2;;
    --env-file) ENV_FILE="$2"; shift 2;;
    --cron-schedule) CRON_SCHEDULE="$2"; shift 2;;
    --foreground) DETACH=false; shift;;
    *) echo "Unknown arg: $1"; exit 1;;
  esac
done

# Build image
docker build -f Dockerfile.cron -t "$IMAGE_NAME" .

# Prepare run args
RUN_ARGS=(--name alkira-aggregate-cron --restart unless-stopped -v "$PWD/alkira-reports":/app/alkira-reports)

if [[ -n "$ENV_FILE" ]]; then
  # mount the provided env file into the container so the wrapper can source it
  RUN_ARGS+=(--env-file "$ENV_FILE")
fi

if [[ -n "$CRON_SCHEDULE" ]]; then
  # pass CRON_SCHEDULE into the container so entrypoint will use it
  RUN_ARGS+=(-e "CRON_SCHEDULE=$CRON_SCHEDULE")
fi

if $DETACH; then
  docker run -d "${RUN_ARGS[@]}" "$IMAGE_NAME"
else
  docker run --rm "${RUN_ARGS[@]}" "$IMAGE_NAME"
fi

echo "Container started (image: $IMAGE_NAME). Logs will be written to alkira-reports/cron.log inside the container (also visible via docker logs)." 
