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

REPORT_SCRIPT="${ALKIRA_AGGREGATE_BUDGET_SCRIPT:-$APP_DIR/alkira_aggregate_budget.py}"

if [[ ! -f "$REPORT_SCRIPT" ]]; then
  echo "ERROR: Could not find alkira_aggregate_budget.py at: $REPORT_SCRIPT" >&2
  echo "Set ALKIRA_AGGREGATE_BUDGET_SCRIPT=/full/path/to/alkira_aggregate_budget.py in .env if it lives elsewhere." >&2
  exit 1
fi

if [[ -x "$REPORT_SCRIPT" ]]; then
  REPORT_COMMAND=("$REPORT_SCRIPT")
else
  REPORT_COMMAND=(python3 "$REPORT_SCRIPT")
fi

"${REPORT_COMMAND[@]}" \
  --connector DEV=33168 \
  --connector QA=36205 \
  --connector QA2=36542 \
  --connector PROD=36608 \
  --budget-total-tb 650 \
  --budget-field rx \
  --output alkira_aggregate_budget.xlsx
