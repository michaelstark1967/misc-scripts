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
    # New CSV layout includes rx/tx per environment and percent-of-budget
    fieldnames = [
        "environment",
        "connector_id",
        "rx_bytes",
        "rx_display",
        "tx_bytes",
        "tx_display",
        "total_bytes",
        "total_display",
        "percent_of_budget",
    ]

    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fieldnames})
        # blank row and totals section
        fh.write("\n")
        fh.write(f"TOTAL_RX_BYTES,{int(round(total['rx_bytes']))}\n")
        fh.write(f"TOTAL_RX_DISPLAY,{total['rx_display']}\n")
        fh.write(f"TOTAL_TX_BYTES,{int(round(total['tx_bytes']))}\n")
        fh.write(f"TOTAL_TX_DISPLAY,{total['tx_display']}\n")
        fh.write(f"TOTAL_USED_BYTES,{int(round(total['total_bytes']))}\n")
        fh.write(f"TOTAL_USED_DISPLAY,{total['total_display']}\n")
        fh.write(f"BUDGET_TOTAL_TB,{total['budget_total_tb']}\n")
        fh.write(f"BUDGET_TOTAL_BYTES,{int(round(total['budget_total_bytes']))}\n")
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

    for name, cid in args.connector:
        context = dict(context_base)
        context["connector_id"] = cid
        endpoint = f"/tenantnetworks/{tenant_network_id}/stats/connectordata/{cid}"
        try:
            response = client.request("GET", endpoint, query=query)
        except Exception as exc:
            print(f"Failed to fetch data for {name} ({cid}): {exc}", file=os.sys.stderr)
            return 1

        try:
            import json

            payload = json.loads(response.text)
        except Exception:
            print(f"Invalid JSON response for {name} ({cid})", file=os.sys.stderr)
            return 1

        rx = transmitted_bytes_from_payload(payload, "rx") or 0.0
        tx = transmitted_bytes_from_payload(payload, "tx") or 0.0
        total = 0.0
        if args.budget_field == "total":
            total = (rx + tx)
        elif args.budget_field == "rx":
            total = rx
        else:
            total = tx

        total_rx += rx
        total_tx += tx

        budget_bytes = tb_to_bytes(args.budget_total_tb)
        percent_of_budget = (total / budget_bytes * 100) if budget_bytes else 0

        rows.append(
            {
                "environment": name,
                "connector_id": cid,
                "rx_bytes": int(round(rx)),
                "rx_display": format_data_amount(rx, args.output_unit),
                "tx_bytes": int(round(tx)),
                "tx_display": format_data_amount(tx, args.output_unit),
                "total_bytes": int(round(total)),
                "total_display": format_data_amount(total, args.output_unit),
                "percent_of_budget": round(percent_of_budget, 4),
            }
        )

    budget_bytes = tb_to_bytes(args.budget_total_tb)
    total_used = total_tx if args.budget_field == "tx" else (total_rx if args.budget_field == "rx" else (total_rx + total_tx))
    remaining_bytes = budget_bytes - total_used
    percent_left = (remaining_bytes / budget_bytes * 100) if budget_bytes else 0

    total_details = {
        "rx_bytes": total_rx,
        "rx_display": format_data_amount(total_rx, args.output_unit) or str(total_rx),
        "tx_bytes": total_tx,
        "tx_display": format_data_amount(total_tx, args.output_unit) or str(total_tx),
        "total_bytes": total_used,
        "total_display": format_data_amount(total_used, args.output_unit) or str(total_used),
        "budget_total_tb": args.budget_total_tb,
        "budget_total_bytes": int(round(budget_bytes)),
        "budget_remaining_bytes": int(round(remaining_bytes)),
        "budget_remaining_display": f"{format_data_amount(abs(remaining_bytes), args.output_unit) or str(abs(remaining_bytes))} {'remaining' if remaining_bytes>=0 else 'over'}",
        "budget_percent_left": round(percent_left, 2),
    }

    output_path = args.output or Path("alkira_aggregate_budget.csv")
    write_aggregate_csv(output_path, rows, total_details)

    details = f"Aggregated connectors: {', '.join([r['environment'] for r in rows])}"
    details += f"\nTotal used ({args.budget_field}): {total_details['used_display']}"
    details += f"\nBudget: {args.budget_total_tb} TB; Remaining: {total_details['budget_remaining_display']} ({total_details['budget_percent_left']:.2f}% left)"

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
