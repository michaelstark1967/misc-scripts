# Alkira Bandwidth Report Puller

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
