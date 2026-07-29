# Alkira Bandwidth Report Puller

Version 1.0

`alkira_bandwidth_report.py` pulls bandwidth stats from an Alkira tenant portal and writes JSON or flattened CSV.

## Setup

Use Alkira API-key auth when possible:

```bash
export ALKIRA_PORTAL="your-tenant.portal.alkira.com"
export ALKIRA_API_KEY="your-api-key"
```

Username/password auth is also supported for compatibility:

```bash
export ALKIRA_USERNAME="you@example.com"
export ALKIRA_PASSWORD="your-password"
```

## Examples

Show command help or common examples:

```bash
./alkira_bandwidth_report.py --help
./alkira_bandwidth_report.py --examples
```

Pull the last 24 hours as JSON:

```bash
./alkira_bandwidth_report.py
```

Pull the default bandwidth-utilization report as CSV:

```bash
./alkira_bandwidth_report.py \
  --start 2026-06-01 \
  --end 2026-06-29 \
  --format csv \
  --output alkira_bandwidth_june.csv
```

CSV output expands Alkira `series` arrays into one row per time bucket and adds readable columns such as `interval_utc`, `interval_local`, `rx_display`, and `tx_display`.

Use `--output-unit` to control the displayed unit and add spreadsheet-friendly numeric columns such as `rx_gigabytes`, `tx_gigabytes`, `rx_terabytes`, or `tx_terabytes`:

```bash
./alkira_bandwidth_report.py \
  --report-type connector-data \
  --connector-id 33276 \
  --cxp USEAST-AZURE-2 \
  --segment "PVH CORP" \
  --output-unit terabytes \
  --format csv \
  --output alkira_connector_data_tb.csv
```

Supported unit values are `auto`, `bytes`, `gigabytes`/`gb`, and `terabytes`/`tb`. The common misspelling `terrabytes` is also accepted.

Pull CXP traffic instead:

```bash
./alkira_bandwidth_report.py \
  --report-type cxp-traffic \
  --format csv \
  --output alkira_cxp_traffic.csv
```

Pull the "Total Connector Traffic Data" summary card from a connector dashboard page:

```bash
./alkira_bandwidth_report.py \
  --report-type connector-data \
  --connector-id 33276 \
  --cxp USEAST-AZURE-2 \
  --segment "PVH CORP" \
  --period custom \
  --start 2026-06-01 \
  --end 2026-06-29 \
  --format csv \
  --output alkira_connector_data.csv
```

Show how much of the 650 TB transmitted-data budget remains since June 1, 2026:

```bash
./alkira_bandwidth_report.py \
  --report-type connector-data \
  --connector-id 33276 \
  --cxp USEAST-AZURE-2 \
  --segment "PVH CORP" \
  --budget-remaining \
  --budget-field rx \
  --output-unit terabytes \
  --format csv \
  --output alkira_connector_budget.csv
```

`--budget-remaining` defaults to a 650 TB budget, starts at `2026-06-01T00:00:00-04:00`, ends at the current time, and subtracts transmitted data (`tx`). Use `--budget-total-tb`, `--budget-start`, or `--budget-field rx|tx|total` to override those assumptions. When `--format csv` is used, the CSV includes budget columns such as `budget_remaining_display` and `budget_remaining_terabytes`.

Use a tenant-specific endpoint:

```bash
./alkira_bandwidth_report.py \
  --endpoint "/tenantnetworks/{tenant_network_id}/stats/v2/connectortraffic" \
  --time-format epoch-seconds \
  --interval 300 \
  --param direction=both
```

The endpoint may be set with `ALKIRA_BANDWIDTH_ENDPOINT` instead of passing `--endpoint`.

## Report Delivery

Email and Teams delivery use a JSON config file. Start from [alkira_report_config.example.json](/Users/michaelstark@pvh.com/Documents/Codex/alkira_report_config.example.json):

```bash
export ALKIRA_SMTP_USERNAME="sender@example.com"
export ALKIRA_SMTP_PASSWORD="smtp-password-or-app-password"
export ALKIRA_REPORT_FROM="sender@example.com"
export ALKIRA_TEAMS_WEBHOOK_URL="https://..."

./alkira_bandwidth_report.py \
  --report-type connector-data \
  --connector-id 33276 \
  --cxp USEAST-AZURE-2 \
  --segment "PVH CORP" \
  --budget-remaining \
  --budget-field rx \
  --output-unit terabytes \
  --format csv \
  --output alkira_connector_budget.csv \
  --delivery-config alkira_report_config.json \
  --send-email \
  --send-teams
```

`--send-email` attaches the generated report file. `--send-teams` posts the run summary to the Teams channel connected to the incoming webhook URL; webhook posts do not upload the CSV itself.

## Notes

The script mirrors the public Alkira Terraform provider's portal/auth behavior:

- Portal host becomes `https://<ALKIRA_PORTAL>/api`.
- API-key auth uses `Authorization: api-key <base64 API key>`.
- Tenant network discovery calls `/tenantnetworksummaries`.

Alkira's public Terraform provider does not expose a bandwidth-report resource. The built-in defaults mirror the read-only dashboard stats APIs used by the portal:

- `bandwidth-utilization` -> `/tenantnetworks/{id}/stats/v2/connectortraffic`
- `connector-data` -> `/tenantnetworks/{id}/stats/connectordata/{connectorId}`
- `connector-traffic` -> `/tenantnetworks/{id}/stats/v2/connectortraffic?detail=true`
- `cxp-traffic` -> `/tenantnetworks/{id}/stats/v2/cxptraffic?detail=true`
- `inter-cxp-traffic` -> `/tenantnetworks/{id}/stats/v2/intercxptraffic`
- `service-traffic` -> `/tenantnetworks/{id}/stats/v2/servicetraffic`
- `internet-traffic` -> `/tenantnetworks/{id}/stats/v2/internettraffic`

Dashboard stats use Unix-second `startTime` and `endTime` values. Chart-style reports also use an `interval` query parameter by default; summary-card reports such as `connector-data` do not. Use `--time-format iso` or `--time-format epoch-ms` if a custom endpoint expects a different format.

## Aggregate connector budget helper

A separate helper script [alkira_aggregate_budget.py](/Users/michaelstark@pvh.com/GitHub/misc-scripts/alkira-reports/alkira_aggregate_budget.py) is provided to aggregate transmitted data across multiple connectors (environments) and report remaining budget. The helper accepts repeated `--connector NAME=CONNECTOR_ID` pairs, sums the chosen traffic field (`tx`, `rx`, or `total`) across the specified connectors, compares the total against a configurable budget (default 650 TB), writes a CSV with per-environment rows and a totals section, and can optionally send email and Teams notifications using the same delivery-config JSON format used by `alkira_bandwidth_report.py`.

Quick usage examples:

One-line (pasteable):

```bash
./alkira_aggregate_budget.py --portal "$ALKIRA_PORTAL" --api-key "$ALKIRA_API_KEY" --connector DEV=33168 --connector QA=36205 --connector QA2=36542 --connector PROD=36608 --budget-total-tb 650 --budget-field rx --output alkira_aggregate_budget.xlsx
```

Multi-line (readable):

```bash
./alkira_aggregate_budget.py \
  --portal "$ALKIRA_PORTAL" --api-key "$ALKIRA_API_KEY" \
  --connector DEV=33168 --connector QA=36205 --connector QA2=36542 --connector PROD=36608 \
  --budget-total-tb 650 --budget-field rx \
  --output alkira_aggregate_budget.xlsx
```

Note:
- The examples write an Excel (.xlsx) workbook (requires `openpyxl`). Install with `pip install openpyxl`.
- This example uses `--budget-field rx` to report received data (RX) for the listed AWS environments. Use `--budget-field tx` to report transmitted data (TX) instead.

Sample CSV output (abbreviated):

```csv
environment,connector_id,rx_24h_bytes,rx_24h_display,tx_24h_bytes,tx_24h_display,total_24h_bytes,total_24h_display,rx_7d_bytes,rx_7d_display,tx_7d_bytes,tx_7d_display,total_7d_bytes,total_7d_display,budget_used_bytes,budget_used_display,percent_of_budget
DEV,33168,12345678901,11.50 GB,9876543210,9.20 GB,20700000000,20.70 GB,23456789012,21.85 GB,34567890123,32.17 GB,54020000000,54.02 GB,103700000000,103.70 GB,0.02
QA,36205,23456789012,21.85 GB,34567890123,32.17 GB,53980000000,53.98 GB,45678901234,42.55 GB,23456789012,21.77 GB,64320000000,64.32 GB,540250000000,540.25 GB,0.08
PROD,36608,0,0 Bytes,0,0 Bytes,0,0 Bytes,0,0 Bytes,1419969081,1.32 GB,1419969081,1.32 GB,1419990706,1.32 GB,0.00
TOTAL,,35802467913,33.35 GB,44422221333,41.37 GB,74224689246,74.72 GB,69135690246,64.41 GB,58024679135,54.06 GB,127261369381,118.47 GB,644000000000,0.58 TB,0.09
```

Wrapper: run_aggregate_and_email.sh

A convenience wrapper is provided to run the aggregate helper and email the generated report using the tuned delivery config.

- Script: run_aggregate_and_email.sh (executable)
- Config: alkira_report_config.json (sample delivery settings)

Example .env (place in the same folder or a secure location and the wrapper will source it):

```bash
# Alkira API
ALKIRA_PORTAL="your-tenant.portal.alkira.com"
ALKIRA_API_KEY="your-api-key"

# SMTP credentials referenced by alkira_report_config.json
ALKIRA_SMTP_USERNAME="sender@example.com"
ALKIRA_SMTP_PASSWORD="smtp-or-app-password"
ALKIRA_REPORT_FROM="sender@example.com"

# Optional overrides (paths)
# ALKIRA_AGGREGATE_BUDGET_SCRIPT="/full/path/to/alkira_aggregate_budget.py"
# ALKIRA_REPORT_DELIVERY_CONFIG="/full/path/to/alkira_report_config.json"
```

Run the wrapper locally:

```bash
./run_aggregate_and_email.sh
```

Cron-friendly example (run nightly at 02:00 UTC)

Edit the crontab for the user (crontab -e) and add:

```cron
0 2 * * * cd /Users/michaelstark@pvh.com/GitHub/misc-scripts/alkira-reports && ./run_aggregate_and_email.sh >> /var/log/alkira_aggregate.log 2>&1
```

Notes

- The wrapper sources .env if present, so store secrets there with appropriate filesystem permissions (chmod 600).
- For .xlsx output the system running the cron job must have openpyxl installed (pip install openpyxl) and a Python environment available. If using a virtualenv, source it at the top of the wrapper before running the script.
- The wrapper defaults to RX and .xlsx; edit the wrapper to change environment connector IDs, budget field, or output path as needed.

Docker / Container

A container image is provided to run the helper on RHEL or other Linux hosts. The image includes openpyxl so .xlsx output works without additional host setup.

- Build with the helper script:

```bash
./docker-build.sh
```

This builds the image `alkira-aggregate:1.0`.

- Run the container (mounts the current directory so outputs persist):

```bash
./docker-run.sh --env-file .env
```

Or with podman directly:

```bash
podman build -t alkira-aggregate:1.0 .
podman run --rm --env-file .env -v "$PWD":/app alkira-aggregate:1.0
```

Notes for containers

- The container expects an `.env` file to be mounted or provided via `--env-file`. Use the provided `.env.example` as a template and ensure the file permissions are secure (chmod 600).
- If you prefer to run a one-off command instead of the wrapper, use `./docker-run.sh --command "./alkira_aggregate_budget.py --help"`.

Version

- Helper script VERSION = 1.0
