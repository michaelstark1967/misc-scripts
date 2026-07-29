#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

if [[ -f "$APP_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$APP_DIR/.env"
  set +a
fi

if [[ -z "${ALKIRA_PORTAL:-}" && -n "${ALKIRA_BASE_URL:-}" ]]; then
  export ALKIRA_PORTAL="$ALKIRA_BASE_URL"
fi

if [[ -z "${ALKIRA_PORTAL:-}" ]]; then
  echo "ERROR: ALKIRA_PORTAL or ALKIRA_BASE_URL must be set in $APP_DIR/.env" >&2
  exit 1
fi

REPORT_SCRIPT="${ALKIRA_BANDWIDTH_REPORT_SCRIPT:-$APP_DIR/alkira_bandwidth_report.py}"

if [[ ! -f "$REPORT_SCRIPT" ]]; then
  echo "ERROR: Could not find alkira_bandwidth_report.py at: $REPORT_SCRIPT" >&2
  echo "Set ALKIRA_BANDWIDTH_REPORT_SCRIPT=/full/path/to/alkira_bandwidth_report.py in .env if it lives elsewhere." >&2
  exit 1
fi

if [[ -x "$REPORT_SCRIPT" ]]; then
  REPORT_COMMAND=("$REPORT_SCRIPT")
else
  REPORT_COMMAND=(python3 "$REPORT_SCRIPT")
fi

"${REPORT_COMMAND[@]}" \
  --report-type connector-data \
  --connector-id 33276 \
  --cxp USEAST-AZURE-2 \
  --segment "PVH CORP" \
  --budget-remaining \
  --budget-field rx \
  --output-unit terabytes \
  --format csv \
  --output alkira_connector_budget.csv
