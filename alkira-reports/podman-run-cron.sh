#!/usr/bin/env bash
# Build and run the cron-enabled container for daily Alkira reports using podman.
# Usage: ./podman-run-cron.sh [--image-name name] [--env-file /path/to/.env] [--cron-schedule "m h dom mon dow"]

set -euo pipefail

IMAGE_NAME="alkira-aggregate-cron:1.0"
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
podman build -f Dockerfile.cron -t "$IMAGE_NAME" .

# Prepare run args
RUN_ARGS=(--name alkira-aggregate-cron -v "$PWD/alkira-reports":/app/alkira-reports)

# Mount host timezone files into the container if available for stricter parity (can be disabled with --no-localtime)
if [[ "$NO_LOCALTIME" != "true" ]]; then
  if [[ -e /etc/localtime ]]; then
    RUN_ARGS+=(--volume /etc/localtime:/etc/localtime:ro)
  fi
  if [[ -e /etc/timezone ]]; then
    RUN_ARGS+=(--volume /etc/timezone:/etc/timezone:ro)
  fi
fi

# Podman supports --restart on newer versions; include if available
RUN_ARGS+=(--restart=unless-stopped)

if [[ -n "$ENV_FILE" ]]; then
  RUN_ARGS+=(--env-file "$ENV_FILE")
fi

if [[ -n "$CRON_SCHEDULE" ]]; then
  RUN_ARGS+=(--env "CRON_SCHEDULE=$CRON_SCHEDULE")
fi

if [[ -n "$TZ_VALUE" ]]; then
  RUN_ARGS+=(--env "TZ=$TZ_VALUE")
fi

if $DETACH; then
  podman run -d "${RUN_ARGS[@]}" "$IMAGE_NAME"
else
  podman run --rm "${RUN_ARGS[@]}" "$IMAGE_NAME"
fi

echo "Podman container started (image: $IMAGE_NAME). Logs will be written to alkira-reports/cron.log inside the container (also visible via podman logs)." 
