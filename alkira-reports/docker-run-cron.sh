#!/usr/bin/env bash
# Build and run the cron-enabled container for daily Alkira reports.
# Usage: ./docker-run-cron.sh [--image-name name] [--env-file /path/to/.env] [--cron-schedule "m h dom mon dow"]

set -euo pipefail

IMAGE_NAME="alkira-aggregate-cron:1.2.1"
ENV_FILE=""
CRON_SCHEDULE=""
TZ_VALUE=""
NO_LOCALTIME=false
DETACH=true

while [[ $# -gt 0 ]]; do
  case $1 in
    --image-name) IMAGE_NAME="$2"; shift 2;;
    --env-file) ENV_FILE="$2"; shift 2;;
    --cron-schedule) CRON_SCHEDULE="$2"; shift 2;;
    --tz) TZ_VALUE="$2"; shift 2;;
    --no-localtime) NO_LOCALTIME=true; shift;;
    --foreground) DETACH=false; shift;;
    *) echo "Unknown arg: $1"; exit 1;;
  esac
done

# If no --tz provided, but host TZ env is set, forward it
if [[ -z "$TZ_VALUE" && -n "${TZ:-}" ]]; then
  TZ_VALUE="$TZ"
fi

# Build image
docker build -f Dockerfile.cron -t "$IMAGE_NAME" .

# Prepare run args
RUN_ARGS=(--name alkira-aggregate-cron --restart unless-stopped -v "$PWD/alkira-reports":/app/alkira-reports)

# Mount host timezone files into the container if available for stricter parity (can be disabled with --no-localtime)
if [[ "$NO_LOCALTIME" != "true" ]]; then
  if [[ -e /etc/localtime ]]; then
    RUN_ARGS+=(-v /etc/localtime:/etc/localtime:ro)
  fi
  if [[ -e /etc/timezone ]]; then
    RUN_ARGS+=(-v /etc/timezone:/etc/timezone:ro)
  fi
fi

if [[ -n "$ENV_FILE" ]]; then
  # mount the provided env file into the container so the wrapper can source it
  RUN_ARGS+=(--env-file "$ENV_FILE")
fi

if [[ -n "$CRON_SCHEDULE" ]]; then
  # pass CRON_SCHEDULE into the container so entrypoint will use it
  RUN_ARGS+=(-e "CRON_SCHEDULE=$CRON_SCHEDULE")
fi

if [[ -n "$TZ_VALUE" ]]; then
  # forward TZ into the container so cron uses the desired timezone
  RUN_ARGS+=(-e "TZ=$TZ_VALUE")
fi

if $DETACH; then
  docker run -d "${RUN_ARGS[@]}" "$IMAGE_NAME"
else
  docker run --rm "${RUN_ARGS[@]}" "$IMAGE_NAME"
fi

echo "Container started (image: $IMAGE_NAME). Logs will be written to alkira-reports/cron.log inside the container (also visible via docker logs)." 
