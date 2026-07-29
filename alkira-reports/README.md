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

Example:

```bash
./alkira_aggregate_budget.py \
  --portal "$ALKIRA_PORTAL" --api-key "$ALKIRA_API_KEY" \
  --connector DEV=33168 --connector QA=36205 --connector QA2=36542 --connector PROD=36608 \
  --budget-total-tb 650 --budget-field rx --output alkira_aggregate_budget.csv

# Note
This example uses --budget-field rx to report received data (RX) for the listed AWS environments. Use --budget-field tx to report transmitted data (TX) instead.
```

Sample CSV output (abbreviated):

```csv
environment,connector_id,rx_24h_bytes,rx_24h_display,tx_24h_bytes,tx_24h_display,total_24h_bytes,total_24h_display,rx_7d_bytes,rx_7d_display,tx_7d_bytes,tx_7d_display,total_7d_bytes,total_7d_display,budget_used_bytes,budget_used_display,percent_of_budget
DEV,33168,12345678901,11.50 GB,9876543210,9.20 GB,20.70 GB,20.70 GB,23456789012,21.85 GB,34567890123,32.17 GB,54.02 GB,54.02 GB,103700000000,103.70 GB,0.02
QA,36205,23456789012,21.85 GB,34567890123,32.17 GB,53.98 GB,53.98 GB,45678901234,42.55 GB,23456789012,21.77 GB,64.32 GB,64.32 GB,540250000000,540.25 GB,0.08

TOTAL_RX_24H_BYTES,35802467913
TOTAL_RX_24H_DISPLAY,33.35 GB
TOTAL_TX_24H_BYTES,44422221333
TOTAL_TX_24H_DISPLAY,41.37 GB
TOTAL_24H_BYTES,74.72 GB

TOTAL_RX_7D_BYTES,69135690246
TOTAL_RX_7D_DISPLAY,64.41 GB
TOTAL_TX_7D_BYTES,58024679135
TOTAL_TX_7D_DISPLAY,54.06 GB
TOTAL_7D_BYTES,118.47 GB

BUDGET_TOTAL_TB,650
BUDGET_TOTAL_BYTES,7136238463523072
BUDGET_USED_BYTES,644000000000
BUDGET_USED_DISPLAY,0.58 TB
BUDGET_REMAINING_BYTES,7135594463523072
BUDGET_REMAINING_DISPLAY,649.42 TB remaining
BUDGET_PERCENT_LEFT,99.83
```

