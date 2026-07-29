#!/usr/bin/env python3
"""Aggregate connector traffic across multiple environments and report budget usage.

Usage examples:
  ./alkira_aggregate_budget.py \
    --portal "$ALKIRA_PORTAL" --api-key "$ALKIRA_API_KEY" \
    --connector DEV=33168 --connector QA=36205 --connector QA2=36542 --connector PROD=36608 \
    --budget-total-tb 650 --budget-field tx --output alkira_aggregate_budget.csv

Delivery: --delivery-config <json> with --send-email and/or --send-teams behave like alkira_bandwidth_report.py
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Import helpers from the main script in the same folder
from alkira_bandwidth_report import (
    AlkiraClient,
    build_query,
    DEFAULT_BUDGET_TOTAL_TB,
    DEFAULT_BUDGET_START,
    DEFAULT_INTERVAL_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    epoch_milliseconds,
    epoch_seconds,
    iso_z,
    load_delivery_config,
    config_section,
    send_email_report,
    send_teams_report,
    parse_datetime,
    parse_key_value,
    transmitted_bytes_from_payload,
    tb_to_bytes,
    format_data_amount,
)


def parse_connector_pair(value: str) -> Tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("Expected NAME=CONNECTOR_ID for --connector")
    name, cid = value.split("=", 1)
    name = name.strip()
    cid = cid.strip()
    if not name or not cid:
        raise argparse.ArgumentTypeError("Connector mapping must be NAME=ID with non-empty values")
    return name, cid


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Aggregate connector traffic and compare to budget")
    p.add_argument("--portal", default=os.getenv("ALKIRA_PORTAL"))
    p.add_argument("--api-key", default=os.getenv("ALKIRA_API_KEY"))
    p.add_argument("--username", default=os.getenv("ALKIRA_USERNAME"))
    p.add_argument("--password", default=os.getenv("ALKIRA_PASSWORD"))
    p.add_argument(
        "--connector",
        action="append",
        type=parse_connector_pair,
        required=True,
        help="Environment=ConnectorID mapping; repeat for each environment",
    )
    p.add_argument("--time-format", choices=("epoch-seconds", "epoch-ms", "iso"), default=os.getenv("ALKIRA_TIME_FORMAT", "epoch-seconds"))
    p.add_argument("--start", type=parse_datetime, help="Start time (ISO or YYYY-MM-DD). Defaults to 24h ago")
    p.add_argument("--end", type=parse_datetime, help="End time. Defaults to now")
    p.add_argument("--interval", default=os.getenv("ALKIRA_INTERVAL", DEFAULT_INTERVAL_SECONDS))
    p.add_argument("--period", default=os.getenv("ALKIRA_PERIOD"))
    p.add_argument("--cxp", default=os.getenv("ALKIRA_CXP"))
    p.add_argument("--segment", default=os.getenv("ALKIRA_SEGMENT"))
    p.add_argument("--param", action="append", help="Extra query parameter KEY=VALUE. Can be repeated.")
    # Dashboard parameter names (compatible with alkira_bandwidth_report.py)
    p.add_argument("--start-param", default="startTime")
    p.add_argument("--end-param", default="endTime")
    p.add_argument("--interval-param", default="interval")
    p.add_argument("--granularity-param", default="granularity")
    p.add_argument("--granularity", help="Optional legacy/custom granularity value for tenant-specific endpoints.")
    p.add_argument("--budget-total-tb", type=float, default=DEFAULT_BUDGET_TOTAL_TB)
    p.add_argument("--budget-field", choices=("tx", "rx", "total"), default="tx")
    p.add_argument("--output", type=Path)
    p.add_argument("--output-unit", default=os.getenv("ALKIRA_OUTPUT_UNIT", "auto"))
    p.add_argument(
        "--delivery-config",
        type=Path,
        default=(Path(os.getenv("ALKIRA_REPORT_DELIVERY_CONFIG")) if os.getenv("ALKIRA_REPORT_DELIVERY_CONFIG") else None),
    )
    p.add_argument("--send-email", action="store_true")
    p.add_argument("--send-teams", action="store_true")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    p.add_argument("--verbose", action="store_true")

    return p


def resolve_time_range(start: Optional[dt.datetime], end: Optional[dt.datetime]) -> Tuple[dt.datetime, dt.datetime]:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    if end is None:
        end = now
    if start is None:
        start = end - dt.timedelta(days=1)
    if start.tzinfo is None:
        start = start.replace(tzinfo=dt.timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=dt.timezone.utc)
    return start.astimezone(dt.timezone.utc), end.astimezone(dt.timezone.utc)


def write_aggregate_csv(path: Path, rows: List[Dict[str, Any]], total: Dict[str, Any]) -> None:
    # CSV layout includes rx/tx per environment for 24h and 7d, plus budget totals (since 2026-06-01)
    fieldnames = [
        "environment",
        "connector_id",
        "rx_24h_bytes",
        "rx_24h_display",
        "tx_24h_bytes",
        "tx_24h_display",
        "total_24h_bytes",
        "total_24h_display",
        "rx_7d_bytes",
        "rx_7d_display",
        "tx_7d_bytes",
        "tx_7d_display",
        "total_7d_bytes",
        "total_7d_display",
        "budget_used_bytes",
        "budget_used_display",
        "percent_of_budget",
    ]

    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fieldnames})
        # blank row and totals section
        fh.write("\n")
        fh.write(f"TOTAL_RX_24H_BYTES,{int(round(total['rx_24h_bytes']))}\n")
        fh.write(f"TOTAL_RX_24H_DISPLAY,{total['rx_24h_display']}\n")
        fh.write(f"TOTAL_TX_24H_BYTES,{int(round(total['tx_24h_bytes']))}\n")
        fh.write(f"TOTAL_TX_24H_DISPLAY,{total['tx_24h_display']}\n")
        fh.write(f"TOTAL_24H_BYTES,{int(round(total['total_24h_bytes']))}\n")
        fh.write(f"TOTAL_24H_DISPLAY,{total['total_24h_display']}\n")

        fh.write(f"TOTAL_RX_7D_BYTES,{int(round(total['rx_7d_bytes']))}\n")
        fh.write(f"TOTAL_RX_7D_DISPLAY,{total['rx_7d_display']}\n")
        fh.write(f"TOTAL_TX_7D_BYTES,{int(round(total['tx_7d_bytes']))}\n")
        fh.write(f"TOTAL_TX_7D_DISPLAY,{total['tx_7d_display']}\n")
        fh.write(f"TOTAL_7D_BYTES,{int(round(total['total_7d_bytes']))}\n")
        fh.write(f"TOTAL_7D_DISPLAY,{total['total_7d_display']}\n")

        fh.write(f"BUDGET_TOTAL_TB,{total['budget_total_tb']}\n")
        fh.write(f"BUDGET_TOTAL_BYTES,{int(round(total['budget_total_bytes']))}\n")
        fh.write(f"BUDGET_USED_BYTES,{int(round(total['budget_used_bytes']))}\n")
        fh.write(f"BUDGET_USED_DISPLAY,{total['budget_used_display']}\n")
        fh.write(f"BUDGET_REMAINING_BYTES,{int(round(total['budget_remaining_bytes']))}\n")
        fh.write(f"BUDGET_REMAINING_DISPLAY,{total['budget_remaining_display']}\n")
        fh.write(f"BUDGET_PERCENT_LEFT,{total['budget_percent_left']}\n")


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.portal:
        parser.error("--portal or ALKIRA_PORTAL is required")

    start, end = resolve_time_range(args.start, args.end)

    client = AlkiraClient(
        portal=args.portal,
        api_key=args.api_key,
        username=args.username,
        password=args.password,
        timeout=args.timeout,
        verbose=args.verbose,
    )

    try:
        client.authenticate()
        tenant_network_id = client.tenant_network_id()
    except Exception as exc:
        print(f"error: {exc}", file=os.sys.stderr)
        return 1

    context_base = {
        "tenant_network_id": tenant_network_id,
        "start": iso_z(start),
        "end": iso_z(end),
        "start_epoch": epoch_seconds(start),
        "end_epoch": epoch_seconds(end),
        "start_ms": epoch_milliseconds(start),
        "end_ms": epoch_milliseconds(end),
        "interval": args.interval or "",
        "granularity": "",
    }

    query = build_query(args, start, end, "connector-data")
    # incorporate extra params
    if args.param:
        extra = dict(parse_key_value(args.param))
        query.update(extra)

    rows: List[Dict[str, Any]] = []
    total_rx = 0.0
    total_tx = 0.0

    # We'll collect three ranges per connector: last 24h, last 7d, and budget window (since DEFAULT_BUDGET_START to now)
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    last24_start = now - dt.timedelta(days=1)
    last24_end = now
    last7_start = now - dt.timedelta(days=7)
    last7_end = now
    budget_start = parse_datetime(DEFAULT_BUDGET_START)
    budget_end = now

    rows = []

    total_rx_24h = total_tx_24h = total_24h = 0.0
    total_rx_7d = total_tx_7d = total_7d = 0.0
    total_budget_used = 0.0

    for name, cid in args.connector:
        endpoint = f"/tenantnetworks/{tenant_network_id}/stats/connectordata/{cid}"

        def fetch_range(start_dt: dt.datetime, end_dt: dt.datetime) -> Optional[dict]:
            q = build_query(args, start_dt, end_dt, "connector-data")
            try:
                resp = client.request("GET", endpoint, query=q)
            except Exception as exc:
                print(f"Failed to fetch data for {name} ({cid}) range {start_dt} - {end_dt}: {exc}", file=os.sys.stderr)
                return None
            try:
                import json

                payload = json.loads(resp.text)
            except Exception:
                print(f"Invalid JSON response for {name} ({cid})", file=os.sys.stderr)
                return None
            return {"payload": payload}

        # 24h
        r24 = fetch_range(last24_start, last24_end)
        rx24 = tx24 = 0.0
        if r24:
            rx24 = transmitted_bytes_from_payload(r24["payload"], "rx") or 0.0
            tx24 = transmitted_bytes_from_payload(r24["payload"], "tx") or 0.0
        total24 = rx24 + tx24 if args.budget_field == "total" else (rx24 if args.budget_field == "rx" else tx24)

        # 7d
        r7 = fetch_range(last7_start, last7_end)
        rx7 = tx7 = 0.0
        if r7:
            rx7 = transmitted_bytes_from_payload(r7["payload"], "rx") or 0.0
            tx7 = transmitted_bytes_from_payload(r7["payload"], "tx") or 0.0
        total7 = rx7 + tx7 if args.budget_field == "total" else (rx7 if args.budget_field == "rx" else tx7)

        # budget window (since DEFAULT_BUDGET_START)
        rb = fetch_range(budget_start, budget_end)
        budget_used = 0.0
        if rb:
            # budget field may be tx/rx/total
            if args.budget_field == "total":
                budget_used = transmitted_bytes_from_payload(rb["payload"], "total") or 0.0
            else:
                budget_used = transmitted_bytes_from_payload(rb["payload"], args.budget_field) or 0.0

        # accumulate totals
        total_rx_24h += rx24
        total_tx_24h += tx24
        total_24h += total24

        total_rx_7d += rx7
        total_tx_7d += tx7
        total_7d += total7

        total_budget_used += budget_used

        budget_bytes = tb_to_bytes(args.budget_total_tb)
        percent_of_budget = (budget_used / budget_bytes * 100) if budget_bytes else 0

        rows.append(
            {
                "environment": name,
                "connector_id": cid,
                "rx_24h_bytes": int(round(rx24)),
                "rx_24h_display": format_data_amount(rx24, args.output_unit),
                "tx_24h_bytes": int(round(tx24)),
                "tx_24h_display": format_data_amount(tx24, args.output_unit),
                "total_24h_bytes": int(round(total24)),
                "total_24h_display": format_data_amount(total24, args.output_unit),
                "rx_7d_bytes": int(round(rx7)),
                "rx_7d_display": format_data_amount(rx7, args.output_unit),
                "tx_7d_bytes": int(round(tx7)),
                "tx_7d_display": format_data_amount(tx7, args.output_unit),
                "total_7d_bytes": int(round(total7)),
                "total_7d_display": format_data_amount(total7, args.output_unit),
                "budget_used_bytes": int(round(budget_used)),
                "budget_used_display": format_data_amount(budget_used, args.output_unit),
                "percent_of_budget": round(percent_of_budget, 2),
            }
        )

    budget_bytes = tb_to_bytes(args.budget_total_tb)
    budget_remaining = budget_bytes - total_budget_used
    percent_left = (budget_remaining / budget_bytes * 100) if budget_bytes else 0

    total_details = {
        "rx_24h_bytes": total_rx_24h,
        "rx_24h_display": format_data_amount(total_rx_24h, args.output_unit) or str(total_rx_24h),
        "tx_24h_bytes": total_tx_24h,
        "tx_24h_display": format_data_amount(total_tx_24h, args.output_unit) or str(total_tx_24h),
        "total_24h_bytes": total_24h,
        "total_24h_display": format_data_amount(total_24h, args.output_unit) or str(total_24h),

        "rx_7d_bytes": total_rx_7d,
        "rx_7d_display": format_data_amount(total_rx_7d, args.output_unit) or str(total_rx_7d),
        "tx_7d_bytes": total_tx_7d,
        "tx_7d_display": format_data_amount(total_tx_7d, args.output_unit) or str(total_tx_7d),
        "total_7d_bytes": total_7d,
        "total_7d_display": format_data_amount(total_7d, args.output_unit) or str(total_7d),

        "budget_total_tb": args.budget_total_tb,
        "budget_total_bytes": int(round(budget_bytes)),
        "budget_used_bytes": int(round(total_budget_used)),
        "budget_used_display": format_data_amount(total_budget_used, args.output_unit) or str(total_budget_used),
        "budget_remaining_bytes": int(round(budget_remaining)),
        "budget_remaining_display": f"{format_data_amount(abs(budget_remaining), args.output_unit) or str(abs(budget_remaining))} {'remaining' if budget_remaining>=0 else 'over'}",
        "budget_percent_left": round(percent_left, 2),
    }

    output_path = args.output or Path("alkira_aggregate_budget.csv")
    write_aggregate_csv(output_path, rows, total_details)

    details = f"Aggregated connectors: {', '.join([r['environment'] for r in rows])}"
    # include 24h and 7d totals and budget window (since DEFAULT_BUDGET_START)
    details += f"\nLast 24h total ({args.budget_field}): {total_details['total_24h_display']}"
    details += f"\nLast 7d total ({args.budget_field}): {total_details['total_7d_display']}"
    details += (
        f"\nBudget (since {DEFAULT_BUDGET_START}): Used {total_details['budget_used_display']}; "
        f"Remaining: {total_details['budget_remaining_display']} ({total_details['budget_percent_left']:.2f}% left)"
    )

    # optional delivery
    if args.send_email or args.send_teams:
        try:
            delivery_config = load_delivery_config(args.delivery_config)
        except Exception as exc:
            print(f"error: {exc}", file=os.sys.stderr)
            return 1

    delivery_results: List[str] = []
    try:
        if args.send_email:
            delivery_results.append(
                send_email_report(
                    config_section(delivery_config, "email"),
                    details,
                    output_path,
                )
            )
        if args.send_teams:
            delivery_results.append(
                send_teams_report(
                    config_section(delivery_config, "teams"),
                    details,
                    output_path,
                )
            )
    except Exception as exc:
        print(f"error: {exc}", file=os.sys.stderr)
        return 1

    for r in delivery_results:
        details += f"\nDelivery: {r}"

    print(f"{details}\nWrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
