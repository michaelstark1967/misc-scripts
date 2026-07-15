#!/usr/bin/env python3
"""Pull bandwidth reports from an Alkira tenant portal.

The script uses Alkira's Terraform-provider-compatible authentication:

  export ALKIRA_PORTAL="tenant.portal.alkira.com"
  export ALKIRA_API_KEY="..."

By default, it pulls Alkira dashboard bandwidth-utilization stats. If Alkira
changes or exposes a tenant-specific reporting endpoint, pass it with --endpoint
or ALKIRA_BANDWIDTH_ENDPOINT. Endpoint templates may include
{tenant_network_id}, {connector_id}, {start}, {end}, {start_epoch},
{end_epoch}, {start_ms}, {end_ms}, and {interval}.
"""

from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
from email.message import EmailMessage
import http.cookiejar
import json
import mimetypes
import os
import smtplib
import ssl
import sys
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Optional, Tuple


DEFAULT_REPORT_TYPE = "bandwidth-utilization"
REPORT_ENDPOINTS = {
    "connector-data": (
        "/tenantnetworks/{tenant_network_id}/stats/connectordata/{connector_id}",
    ),
    "bandwidth-utilization": (
        "/tenantnetworks/{tenant_network_id}/stats/v2/connectortraffic",
        "/tenantnetworks/{tenant_network_id}/stats/v2/connectortraffic?detail=true",
    ),
    "connector-traffic": (
        "/tenantnetworks/{tenant_network_id}/stats/v2/connectortraffic?detail=true",
        "/tenantnetworks/{tenant_network_id}/stats/v2/connectortraffic",
    ),
    "cxp-traffic": (
        "/tenantnetworks/{tenant_network_id}/stats/v2/cxptraffic?detail=true",
    ),
    "inter-cxp-traffic": (
        "/tenantnetworks/{tenant_network_id}/stats/v2/intercxptraffic",
    ),
    "service-traffic": (
        "/tenantnetworks/{tenant_network_id}/stats/v2/servicetraffic",
    ),
    "internet-traffic": (
        "/tenantnetworks/{tenant_network_id}/stats/v2/internettraffic",
    ),
    "top-connector-traffic": (
        "/tenantnetworks/{tenant_network_id}/stats/topconnectortraffic?detail=true",
    ),
    "top-talkers": (
        "/tenantnetworks/{tenant_network_id}/stats/toptalkers",
    ),
    "top-applications": (
        "/tenantnetworks/{tenant_network_id}/stats/topapplications",
    ),
    "cxp-data": (
        "/tenantnetworks/{tenant_network_id}/stats/cxpdata",
    ),
    "cloud-data": (
        "/tenantnetworks/{tenant_network_id}/stats/cxpclouddata",
    ),
    "branch-data": (
        "/tenantnetworks/{tenant_network_id}/stats/cxpbranchdata",
    ),
    "services-data": (
        "/tenantnetworks/{tenant_network_id}/stats/cxpsvcdata",
    ),
    "inter-cxp-data": (
        "/tenantnetworks/{tenant_network_id}/stats/intercxpdata",
    ),
}
TRAFFIC_REPORT_TYPES = {
    "connector-traffic",
    "cxp-traffic",
    "inter-cxp-traffic",
    "service-traffic",
    "internet-traffic",
    "top-connector-traffic",
    "top-talkers",
    "top-applications",
}
DATA_REPORT_TYPES = {
    "connector-data",
    "cxp-data",
    "cloud-data",
    "branch-data",
    "services-data",
    "inter-cxp-data",
}
MISSING_ENDPOINT_STATUSES = {400, 404, 405}

RETRY_STATUSES = {429, 500, 502, 503, 504}
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_INTERVAL_SECONDS = "300"
DEFAULT_MAX_ITEMS = "10"
DEFAULT_BUDGET_START = "2026-06-01T00:00:00-04:00"
DEFAULT_BUDGET_TOTAL_TB = 650.0
BYTES_PER_GB = 1024**3
BYTES_PER_TB = 1024**4
DATA_UNIT_ALIASES = {
    "auto": "auto",
    "b": "bytes",
    "byte": "bytes",
    "bytes": "bytes",
    "gb": "gigabytes",
    "gigabyte": "gigabytes",
    "gigabytes": "gigabytes",
    "tb": "terabytes",
    "terabyte": "terabytes",
    "terabytes": "terabytes",
    "terrabyte": "terabytes",
    "terrabytes": "terabytes",
}
DATA_UNIT_DIVISORS = {
    "bytes": 1,
    "gigabytes": BYTES_PER_GB,
    "terabytes": BYTES_PER_TB,
}
DATA_UNIT_LABELS = {
    "bytes": "Bytes",
    "gigabytes": "GB",
    "terabytes": "TB",
}
EXAMPLES = """\
Examples:
  Show full option help:
    ./alkira_bandwidth_report.py --help

  Show remaining 650 TB transmitted-data budget since June 1, 2026:
    ./alkira_bandwidth_report.py \\
      --report-type connector-data \\
      --connector-id 33276 \\
      --cxp USEAST-AZURE-2 \\
      --segment "PVH CORP" \\
      --budget-remaining \\
      --budget-field rx \\
      --output-unit terabytes \\
      --format csv \\
      --output alkira_connector_budget.csv

  Pull the connector dashboard summary card for a custom date range:
    ./alkira_bandwidth_report.py \\
      --report-type connector-data \\
      --connector-id 33276 \\
      --cxp USEAST-AZURE-2 \\
      --segment "PVH CORP" \\
      --period custom \\
      --start "2026-06-01T00:00:00-04:00" \\
      --end "2026-06-29T23:59:59-04:00" \\
      --output-unit gigabytes \\
      --format csv \\
      --output alkira_connector_data.csv

  Pull bandwidth-utilization chart data for the last 24 hours:
    ./alkira_bandwidth_report.py \\
      --report-type bandwidth-utilization \\
      --format csv \\
      --output alkira_bandwidth.csv

  Email the CSV and post a summary to a Teams channel:
    ./alkira_bandwidth_report.py \\
      --report-type connector-data \\
      --connector-id 33276 \\
      --cxp USEAST-AZURE-2 \\
      --segment "PVH CORP" \\
      --budget-remaining \\
      --budget-field rx \\
      --output-unit terabytes \\
      --format csv \\
      --output alkira_connector_budget.csv \\
      --delivery-config alkira_report_config.json \\
      --send-email \\
      --send-teams
"""


class AlkiraError(RuntimeError):
    """Raised for Alkira API and configuration errors."""


class HttpResponse:
    def __init__(self, status: int, headers: dict[str, str], body: bytes):
        self.status = status
        self.headers = headers
        self.body = body

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


class AlkiraClient:
    def __init__(
        self,
        portal: str,
        api_key: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        verbose: bool = False,
    ) -> None:
        self.api_base = normalize_api_base(portal)
        self.api_key = api_key
        self.username = username
        self.password = password
        self.timeout = timeout
        self.verbose = verbose
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )
        self.authorization = self._build_authorization()

    def _build_authorization(self) -> Optional[str]:
        if self.api_key:
            encoded = base64.b64encode(self.api_key.encode("utf-8")).decode("ascii")
            return f"api-key {encoded}"

        if self.username and self.password:
            encoded = base64.b64encode(
                f"{self.username}:{self.password}".encode("utf-8")
            ).decode("ascii")
            return f"basic {encoded}"

        return None

    def authenticate(self) -> None:
        if self.authorization:
            return

        raise AlkiraError(
            "Missing credentials. Set ALKIRA_API_KEY or both "
            "ALKIRA_USERNAME and ALKIRA_PASSWORD."
        )

    def tenant_network_id(self) -> str:
        response = self.request("GET", "/tenantnetworksummaries", expected_statuses={200})
        payload = parse_json_response(response, "/tenantnetworksummaries")

        if not isinstance(payload, list) or not payload:
            raise AlkiraError("No tenant network summaries were returned by Alkira.")

        tenant_id = payload[0].get("id") if isinstance(payload[0], dict) else None
        if tenant_id is None:
            raise AlkiraError("Alkira tenant network summary did not include an id.")

        return str(tenant_id)

    def request(
        self,
        method: str,
        endpoint: str,
        query: Optional[dict[str, str]] = None,
        body: Optional[dict[str, Any]] = None,
        raw_body: Optional[bytes] = None,
        use_authorization: bool = True,
        expected_statuses: Optional[set[int]] = None,
    ) -> HttpResponse:
        url = self._url(endpoint, query)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/csv, text/plain;q=0.8, */*;q=0.5",
            "x-ak-request-id": f"alkira-bandwidth-{uuid.uuid4()}",
        }
        if use_authorization and self.authorization:
            headers["Authorization"] = self.authorization

        data = raw_body
        if body is not None:
            data = json.dumps(body).encode("utf-8")

        attempt = 0
        while True:
            attempt += 1
            if self.verbose:
                print(f"{method} {redact_url(url)}", file=sys.stderr)

            request = urllib.request.Request(
                url,
                data=data,
                headers=headers,
                method=method.upper(),
            )

            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    result = HttpResponse(
                        response.status,
                        dict(response.headers.items()),
                        response.read(),
                    )
            except urllib.error.HTTPError as exc:
                result = HttpResponse(exc.code, dict(exc.headers.items()), exc.read())
            except urllib.error.URLError as exc:
                raise AlkiraError(f"Failed to reach Alkira portal: {exc}") from exc

            if expected_statuses and result.status in expected_statuses:
                return result
            if not expected_statuses and 200 <= result.status <= 299:
                return result

            if (
                result.status in RETRY_STATUSES
                and not is_missing_endpoint_response(result)
                and attempt <= 5
            ):
                sleep_seconds = retry_after_seconds(result.headers, attempt)
                if self.verbose:
                    print(
                        f"Retrying after HTTP {result.status} in {sleep_seconds}s",
                        file=sys.stderr,
                    )
                time.sleep(sleep_seconds)
                continue

            if expected_statuses:
                expected = ", ".join(str(status) for status in sorted(expected_statuses))
                raise AlkiraError(
                    f"Alkira API returned HTTP {result.status}; expected {expected}. "
                    f"Response: {trim_response(result.text)}"
                )

            raise AlkiraEndpointError(
                result.status,
                f"HTTP {result.status}: {trim_response(result.text)}",
            )

    def _url(self, endpoint: str, query: Optional[dict[str, str]] = None) -> str:
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            base = endpoint
        else:
            base = f"{self.api_base}/{endpoint.lstrip('/')}"

        if not query:
            return base

        separator = "&" if urllib.parse.urlparse(base).query else "?"
        return f"{base}{separator}{urllib.parse.urlencode(query)}"


class AlkiraEndpointError(AlkiraError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def normalize_api_base(portal: str) -> str:
    portal = portal.strip().rstrip("/")
    if not portal:
        raise AlkiraError("ALKIRA_PORTAL is required.")

    if not portal.startswith(("http://", "https://")):
        portal = f"https://{portal}"

    if portal.endswith("/api"):
        return portal

    return f"{portal}/api"


def redact_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    redacted = [
        (key, "REDACTED" if "key" in key.lower() or "token" in key.lower() else value)
        for key, value in query
    ]
    return urllib.parse.urlunsplit(
        parsed._replace(query=urllib.parse.urlencode(redacted))
    )


def retry_after_seconds(headers: dict[str, str], attempt: int) -> int:
    retry_after = headers.get("Retry-After") or headers.get("retry-after")
    if retry_after:
        try:
            return max(1, int(retry_after))
        except ValueError:
            pass

    return min(30, 2**attempt)


def is_missing_endpoint_response(response: HttpResponse) -> bool:
    if response.status in MISSING_ENDPOINT_STATUSES:
        return True

    if response.status == 500 and "No static resource" in response.text:
        return True

    return False


def is_missing_endpoint_error(exc: AlkiraEndpointError) -> bool:
    if exc.status in MISSING_ENDPOINT_STATUSES:
        return True

    return exc.status == 500 and "No static resource" in str(exc)


def parse_json_response(response: HttpResponse, label: str) -> Any:
    try:
        return json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise AlkiraError(f"{label} returned non-JSON data: {response.text[:200]}") from exc


def trim_response(text: str, limit: int = 700) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def parse_datetime(value: str) -> dt.datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"

    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed_date = dt.date.fromisoformat(normalized)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"Invalid date/time '{value}'. Use YYYY-MM-DD or ISO-8601."
            ) from exc
        parsed = dt.datetime.combine(parsed_date, dt.time.min)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def iso_z(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def epoch_seconds(value: dt.datetime) -> str:
    return str(int(value.astimezone(dt.timezone.utc).timestamp()))


def epoch_milliseconds(value: dt.datetime) -> str:
    return str(int(value.astimezone(dt.timezone.utc).timestamp() * 1000))


def format_time_param(value: dt.datetime, time_format: str) -> str:
    if time_format == "iso":
        return iso_z(value)
    if time_format == "epoch-ms":
        return epoch_milliseconds(value)
    return epoch_seconds(value)


def parse_output_unit(value: str) -> str:
    unit = value.strip().lower()
    if unit in DATA_UNIT_ALIASES:
        return DATA_UNIT_ALIASES[unit]

    valid = ", ".join(("auto", "bytes", "gigabytes", "terabytes"))
    raise argparse.ArgumentTypeError(
        f"Invalid output unit '{value}'. Use one of: {valid}."
    )


def format_bytes(value: Any, precision: int = 2) -> Optional[str]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if number <= 0:
        return "0 Bytes"

    units = ("Bytes", "KB", "MB", "GB", "TB", "PB")
    size = 1024.0
    unit_index = 0
    while number >= size and unit_index < len(units) - 1:
        number /= size
        unit_index += 1

    if unit_index == 0:
        return f"{int(number)} {units[unit_index]}"

    return f"{number:.{precision}f} {units[unit_index]}"


def convert_bytes(value: Any, unit: str) -> Optional[float]:
    number = numeric_value(value)
    if number is None or unit == "auto":
        return None

    divisor = DATA_UNIT_DIVISORS[unit]
    converted = number / divisor
    if unit == "bytes":
        return int(round(converted))
    return round(converted, 6)


def format_data_amount(
    value: Any,
    unit: str = "auto",
    precision: int = 2,
) -> Optional[str]:
    if unit == "auto":
        return format_bytes(value, precision=precision)

    converted = convert_bytes(value, unit)
    if converted is None:
        return None

    label = DATA_UNIT_LABELS[unit]
    if unit == "bytes":
        return f"{converted} {label}"
    return f"{converted:.{precision}f} {label}"


def tb_to_bytes(value: float) -> float:
    return value * BYTES_PER_TB


def numeric_value(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_key_value(values: Iterable[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise argparse.ArgumentTypeError(
                f"Expected KEY=VALUE for parameter '{value}'."
            )
        key, item = value.split("=", 1)
        key = key.strip()
        if not key:
            raise argparse.ArgumentTypeError(f"Parameter '{value}' has an empty key.")
        parsed[key] = item
    return parsed


def load_delivery_config(path: Optional[Path]) -> dict[str, Any]:
    if path is None:
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AlkiraError(f"Delivery config not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AlkiraError(f"Delivery config is not valid JSON: {path}") from exc

    if not isinstance(payload, dict):
        raise AlkiraError("Delivery config must be a JSON object.")

    return payload


def config_section(config: dict[str, Any], name: str) -> dict[str, Any]:
    section = config.get(name) or {}
    if not isinstance(section, dict):
        raise AlkiraError(f"Delivery config section '{name}' must be an object.")
    return section


def config_value(
    config: dict[str, Any],
    key: str,
    default: Optional[Any] = None,
) -> Optional[Any]:
    env_name = config.get(f"{key}_env")
    if env_name:
        return os.getenv(str(env_name))
    return config.get(key, default)


def required_config_value(config: dict[str, Any], key: str, label: str) -> Any:
    value = config_value(config, key)
    if value in (None, ""):
        raise AlkiraError(f"Missing required delivery config value: {label}")
    return value


def config_bool(config: dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def config_int(config: dict[str, Any], key: str, default: int) -> int:
    value = config.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise AlkiraError(f"Delivery config value '{key}' must be an integer.") from exc


def config_list(config: dict[str, Any], key: str) -> list[str]:
    value = config_value(config, key)
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raise AlkiraError(f"Delivery config value '{key}' must be a string or list.")


def delivery_text(
    details: str,
    output_path: Path,
    prefix: Optional[str] = None,
) -> str:
    parts = []
    if prefix:
        parts.append(prefix.strip())
    parts.append(details)
    parts.append(f"Report file: {output_path.name}")
    return "\n\n".join(part for part in parts if part)


def send_email_report(
    config: dict[str, Any],
    details: str,
    output_path: Path,
) -> str:
    smtp_host = str(required_config_value(config, "smtp_host", "email.smtp_host"))
    smtp_port = config_int(config, "smtp_port", 587)
    sender = str(required_config_value(config, "from", "email.from"))
    to_addresses = config_list(config, "to")
    cc_addresses = config_list(config, "cc")
    bcc_addresses = config_list(config, "bcc")
    recipients = to_addresses + cc_addresses + bcc_addresses
    if not recipients:
        raise AlkiraError("Missing required delivery config value: email.to")

    subject = str(config_value(config, "subject", "Alkira Bandwidth Report"))
    body_prefix = config_value(config, "body")
    message = EmailMessage()
    message["From"] = sender
    message["To"] = ", ".join(to_addresses)
    if cc_addresses:
        message["Cc"] = ", ".join(cc_addresses)
    message["Subject"] = subject
    message.set_content(delivery_text(details, output_path, body_prefix))

    if config_bool(config, "attach_report", True):
        content_type, _encoding = mimetypes.guess_type(str(output_path))
        maintype, subtype = (content_type or "application/octet-stream").split("/", 1)
        message.add_attachment(
            output_path.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=output_path.name,
        )

    username = config_value(config, "smtp_username")
    password = config_value(config, "smtp_password")
    use_ssl = config_bool(config, "use_ssl", False)
    use_tls = config_bool(config, "use_tls", not use_ssl)
    timeout = config_int(config, "timeout", DEFAULT_TIMEOUT_SECONDS)
    context = ssl.create_default_context()

    smtp_class = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with smtp_class(smtp_host, smtp_port, timeout=timeout) as smtp:
        if use_tls and not use_ssl:
            smtp.starttls(context=context)
        if username:
            if not password:
                raise AlkiraError(
                    "Missing required delivery config value: email.smtp_password"
                )
            smtp.login(str(username), str(password))
        smtp.send_message(message, to_addrs=recipients)

    return f"emailed report to {', '.join(to_addresses)}"


def send_teams_report(
    config: dict[str, Any],
    details: str,
    output_path: Path,
) -> str:
    webhook_url = str(
        required_config_value(config, "webhook_url", "teams.webhook_url")
    )
    title = str(config_value(config, "title", "Alkira Bandwidth Report"))
    text = config_value(config, "text")
    include_details = config_bool(config, "include_details", True)
    body = delivery_text(details if include_details else "", output_path, text)
    payload = {
        "text": f"**{title}**\n\n{body}",
    }
    timeout = config_int(config, "timeout", DEFAULT_TIMEOUT_SECONDS)
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            if not 200 <= status <= 299:
                raise AlkiraError(f"Teams webhook returned HTTP {status}.")
    except urllib.error.HTTPError as exc:
        response_text = exc.read().decode("utf-8", errors="replace")
        raise AlkiraError(
            f"Teams webhook returned HTTP {exc.code}: {response_text}"
        ) from exc
    except urllib.error.URLError as exc:
        raise AlkiraError(f"Failed to reach Teams webhook: {exc}") from exc

    channel = config_value(config, "channel")
    if channel:
        return f"sent Teams notification to {channel}"
    return "sent Teams notification"


def report_default_params(report_type: str) -> dict[str, str]:
    if report_type == "bandwidth-utilization":
        return {
            "showUtilization": "true",
            "bwQueryType": "MAX",
            "numTopConnectors": "1000",
        }

    if report_type == "connector-data":
        return {}

    if report_type in TRAFFIC_REPORT_TYPES:
        return {"showBandwidth": "true"}

    if report_type in DATA_REPORT_TYPES:
        return {}

    return {}


def report_uses_interval(report_type: str) -> bool:
    return report_type == "bandwidth-utilization" or report_type in TRAFFIC_REPORT_TYPES


def build_query(
    args: argparse.Namespace,
    start: dt.datetime,
    end: dt.datetime,
    report_type: str,
) -> dict[str, str]:
    query = report_default_params(report_type)
    query.update(parse_key_value(args.param or []))
    query[args.start_param] = format_time_param(start, args.time_format)
    query[args.end_param] = format_time_param(end, args.time_format)
    period = getattr(args, "period", None)
    cxp = getattr(args, "cxp", None)
    segment = getattr(args, "segment", None)
    max_items = getattr(args, "max_items", None)
    traffic_bandwidth_type = getattr(args, "traffic_bandwidth_type", None)
    if period:
        query["period"] = period
    if cxp:
        query["cxp"] = cxp
    if segment:
        query["segment"] = segment
    if max_items:
        query["maxItems"] = max_items
    if traffic_bandwidth_type:
        query["trafficBandwidthType"] = traffic_bandwidth_type
    interval = getattr(args, "interval", None)
    if interval is None and report_uses_interval(report_type):
        interval = DEFAULT_INTERVAL_SECONDS
    if interval:
        query[args.interval_param] = interval
    if args.granularity:
        query[args.granularity_param] = args.granularity
    return query


def render_endpoint(endpoint: str, context: dict[str, str]) -> str:
    try:
        return endpoint.format(**context)
    except KeyError as exc:
        missing = exc.args[0]
        raise AlkiraError(f"Endpoint template references unknown value {{{missing}}}.") from exc


def choose_report_endpoint(
    client: AlkiraClient,
    endpoints: list[str],
    context: dict[str, str],
    query: dict[str, str],
) -> Tuple[str, HttpResponse]:
    failures: list[str] = []

    for endpoint in endpoints:
        rendered = render_endpoint(endpoint, context)
        try:
            response = client.request("GET", rendered, query=query)
            return rendered, response
        except AlkiraEndpointError as exc:
            failures.append(f"{rendered}: {exc}")
            if not is_missing_endpoint_error(exc):
                raise

    failure_text = "\n  - ".join(failures)
    raise AlkiraError(
        "Could not pull a bandwidth report from the tested endpoints. "
        "Set --endpoint or ALKIRA_BANDWIDTH_ENDPOINT to the endpoint used by "
        f"your Alkira tenant/API version.\n  - {failure_text}"
    )


def content_type(response: HttpResponse) -> str:
    return (
        response.headers.get("Content-Type")
        or response.headers.get("content-type")
        or ""
    ).lower()


def extract_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [record if isinstance(record, dict) else {"value": record} for record in payload]

    if isinstance(payload, dict):
        for key in (
            "items",
            "data",
            "results",
            "records",
            "series",
            "content",
            "bandwidth",
            "report",
        ):
            value = payload.get(key)
            if isinstance(value, list):
                return [
                    record if isinstance(record, dict) else {"value": record}
                    for record in value
                ]
        return [payload]

    return [{"value": payload}]


def interval_timestamp(value: Any, local: bool = False) -> Optional[str]:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None

    if timestamp > 10_000_000_000:
        timestamp = timestamp / 1000

    try:
        parsed = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None

    if local:
        parsed = parsed.astimezone()

    return parsed.replace(microsecond=0).isoformat()


def decorate_record(record: dict[str, Any], output_unit: str = "auto") -> dict[str, Any]:
    decorated = dict(record)

    interval = decorated.get("interval")
    if interval is not None:
        interval_utc = interval_timestamp(interval)
        interval_local = interval_timestamp(interval, local=True)
        if interval_utc:
            decorated["interval_utc"] = interval_utc
        if interval_local:
            decorated["interval_local"] = interval_local

    for direction in ("rx", "tx"):
        converted_value = convert_bytes(decorated.get(direction), output_unit)
        if converted_value is not None:
            decorated[f"{direction}_{output_unit}"] = converted_value

        display_value = format_data_amount(decorated.get(direction), output_unit)
        if display_value is not None:
            decorated[f"{direction}_display"] = display_value

    return decorated


def expand_series_records(
    records: list[dict[str, Any]],
    output_unit: str = "auto",
) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []

    for record in records:
        series = record.get("series")
        if not isinstance(series, list):
            expanded.append(decorate_record(record, output_unit))
            continue

        parent = {key: value for key, value in record.items() if key != "series"}
        if not series:
            expanded.append(decorate_record(parent, output_unit))
            continue

        for sample in series:
            if isinstance(sample, dict):
                expanded.append(decorate_record({**parent, **sample}, output_unit))
            else:
                expanded.append(
                    decorate_record({**parent, "series_value": sample}, output_unit)
                )

    return expanded


def flatten_record(record: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for key, value in record.items():
        full_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flattened.update(flatten_record(value, full_key))
        elif isinstance(value, list):
            flattened[full_key] = json.dumps(value, separators=(",", ":"))
        else:
            flattened[full_key] = value

    return flattened


def ordered_fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    preferred = [
        "name",
        "cxp",
        "segment",
        "unit",
        "interval",
        "interval_utc",
        "interval_local",
        "rx",
        "rx_bytes",
        "rx_gigabytes",
        "rx_terabytes",
        "rx_display",
        "tx",
        "tx_bytes",
        "tx_gigabytes",
        "tx_terabytes",
        "tx_display",
        "budget_field",
        "budget_total_bytes",
        "budget_total_gigabytes",
        "budget_total_terabytes",
        "budget_total_display",
        "budget_used_bytes",
        "budget_used_gigabytes",
        "budget_used_terabytes",
        "budget_used_display",
        "budget_remaining_bytes",
        "budget_remaining_gigabytes",
        "budget_remaining_terabytes",
        "budget_remaining_display",
        "budget_percent_left",
        "budget_status",
        "value",
    ]
    keys = {key for row in rows for key in row.keys()}
    ordered = [key for key in preferred if key in keys]
    ordered.extend(sorted(keys - set(ordered)))
    return ordered


def write_json(path: Path, response: HttpResponse) -> None:
    payload = parse_json_response(response, "bandwidth report")
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(
    path: Path,
    response: HttpResponse,
    output_unit: str = "auto",
    extra_columns: Optional[dict[str, Any]] = None,
) -> int:
    payload = parse_json_response(response, "bandwidth report")
    rows = []
    for record in expand_series_records(extract_records(payload), output_unit):
        flattened = flatten_record(record)
        if extra_columns:
            flattened.update(extra_columns)
        rows.append(flattened)
    fieldnames = ordered_fieldnames(rows)

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return len(rows)


def write_raw(path: Path, response: HttpResponse) -> None:
    path.write_bytes(response.body)


def traffic_summary(response: HttpResponse, output_unit: str = "auto") -> Optional[str]:
    try:
        payload = parse_json_response(response, "bandwidth report")
    except AlkiraError:
        return None

    records = extract_records(payload)
    if not records:
        return None

    record = records[0]
    rx = format_data_amount(record.get("rx"), output_unit)
    tx = format_data_amount(record.get("tx"), output_unit)
    parts = []
    if rx is not None:
        parts.append(f"{rx} RX")
    if tx is not None:
        parts.append(f"{tx} TX")

    return ", ".join(parts) if parts else None


def transmitted_bytes_from_payload(payload: Any, field: str = "tx") -> Optional[float]:
    total = 0.0
    found = False

    for record in expand_series_records(extract_records(payload)):
        fields = ("rx", "tx") if field == "total" else (field,)
        for item in fields:
            value = numeric_value(record.get(item))
            if value is None:
                continue
            total += value
            found = True

    return total if found else None


def budget_remaining_details(
    response: HttpResponse,
    budget_total_tb: float = DEFAULT_BUDGET_TOTAL_TB,
    field: str = "tx",
    output_unit: str = "auto",
) -> Optional[dict[str, Any]]:
    try:
        payload = parse_json_response(response, "bandwidth report")
    except AlkiraError:
        return None

    used_bytes = transmitted_bytes_from_payload(payload, field)
    if used_bytes is None:
        return None

    budget_bytes = tb_to_bytes(budget_total_tb)
    remaining_bytes = budget_bytes - used_bytes
    percent_left = (remaining_bytes / budget_bytes * 100) if budget_bytes else 0

    budget_display = (
        format_data_amount(budget_bytes, output_unit) or f"{budget_total_tb} TB"
    )
    used_display = format_data_amount(used_bytes, output_unit) or str(used_bytes)
    remaining_display = (
        format_data_amount(abs(remaining_bytes), output_unit)
        or str(abs(remaining_bytes))
    )
    label = "RX + TX" if field == "total" else field.upper()
    status = "over" if remaining_bytes < 0 else "remaining"

    details: dict[str, Any] = {
        "budget_field": label,
        "budget_total_bytes": int(round(budget_bytes)),
        "budget_total_display": budget_display,
        "budget_used_bytes": int(round(used_bytes)),
        "budget_used_display": used_display,
        "budget_remaining_bytes": int(round(remaining_bytes)),
        "budget_remaining_display": f"{remaining_display} {status}",
        "budget_percent_left": round(percent_left, 2),
        "budget_status": status,
    }

    if output_unit in DATA_UNIT_DIVISORS and output_unit != "bytes":
        details[f"budget_total_{output_unit}"] = convert_bytes(
            budget_bytes,
            output_unit,
        )
        details[f"budget_used_{output_unit}"] = convert_bytes(
            used_bytes,
            output_unit,
        )
        details[f"budget_remaining_{output_unit}"] = convert_bytes(
            remaining_bytes,
            output_unit,
        )

    return details


def budget_remaining_summary_from_details(details: dict[str, Any]) -> str:
    percent_left = numeric_value(details.get("budget_percent_left")) or 0
    if details.get("budget_status") == "over":
        return (
            f"Budget: {details['budget_total_display']}; "
            f"Used {details['budget_field']}: {details['budget_used_display']}; "
            f"{details['budget_remaining_display']} ({abs(percent_left):.2f}% over)"
        )

    return (
        f"Budget: {details['budget_total_display']}; "
        f"Used {details['budget_field']}: {details['budget_used_display']}; "
        f"{details['budget_remaining_display']} ({percent_left:.2f}% left)"
    )


def budget_remaining_summary(
    response: HttpResponse,
    budget_total_tb: float = DEFAULT_BUDGET_TOTAL_TB,
    field: str = "tx",
    output_unit: str = "auto",
) -> Optional[str]:
    details = budget_remaining_details(
        response,
        budget_total_tb=budget_total_tb,
        field=field,
        output_unit=output_unit,
    )
    if details is None:
        return None

    return budget_remaining_summary_from_details(details)


def default_output_path(output_format: str, start: dt.datetime, end: dt.datetime) -> Path:
    safe_start = iso_z(start).replace(":", "").replace("-", "")
    safe_end = iso_z(end).replace(":", "").replace("-", "")
    suffix = "csv" if output_format == "csv" else "json"
    return Path(f"alkira_bandwidth_{safe_start}_{safe_end}.{suffix}")


def resolve_output_format(args_format: str, response: HttpResponse) -> str:
    if args_format != "auto":
        return args_format

    ctype = content_type(response)
    if "csv" in ctype:
        return "raw"
    return "json"


def resolve_time_range(
    args: argparse.Namespace,
    now: dt.datetime,
) -> tuple[dt.datetime, dt.datetime]:
    end = args.end or now
    if args.budget_remaining:
        start = args.start or args.budget_start or parse_datetime(DEFAULT_BUDGET_START)
    else:
        start = args.start or (end - dt.timedelta(days=1))
    return start, end


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pull Alkira bandwidth reports to JSON or CSV.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--examples",
        action="store_true",
        help="Print common usage examples and exit.",
    )
    parser.add_argument(
        "--budget-remaining",
        action="store_true",
        help=(
            "Use the 650 TB project budget window, subtract transmitted data, "
            "and print data left in budget. Defaults to 2026-06-01 through now."
        ),
    )
    parser.add_argument(
        "--budget-total-tb",
        type=float,
        default=DEFAULT_BUDGET_TOTAL_TB,
        help="Total project data budget in TB for --budget-remaining.",
    )
    parser.add_argument(
        "--budget-start",
        type=parse_datetime,
        help=(
            "Budget window start. Defaults to 2026-06-01T00:00:00-04:00 "
            "when --budget-remaining is used."
        ),
    )
    parser.add_argument(
        "--budget-field",
        choices=("tx", "rx", "total"),
        default="tx",
        help="Traffic field to subtract from the budget.",
    )
    parser.add_argument("--portal", default=os.getenv("ALKIRA_PORTAL"))
    parser.add_argument("--api-key", default=os.getenv("ALKIRA_API_KEY"))
    parser.add_argument("--username", default=os.getenv("ALKIRA_USERNAME"))
    parser.add_argument("--password", default=os.getenv("ALKIRA_PASSWORD"))
    parser.add_argument(
        "--tenant-network-id",
        default=os.getenv("ALKIRA_TENANT_NETWORK_ID"),
        help="Skip tenant network discovery and use this tenant network id.",
    )
    parser.add_argument(
        "--connector-id",
        default=os.getenv("ALKIRA_CONNECTOR_ID"),
        help="Connector id for connector-data reports. In the portal URL, this is the id after /connectors/.",
    )
    parser.add_argument(
        "--endpoint",
        action="append",
        default=(
            [os.getenv("ALKIRA_BANDWIDTH_ENDPOINT")]
            if os.getenv("ALKIRA_BANDWIDTH_ENDPOINT")
            else None
        ),
        help=(
            "Bandwidth report endpoint path or URL. Can be repeated. Supports "
            "{tenant_network_id}, {connector_id}, {start}, {end}, "
            "{start_epoch}, {end_epoch}, {start_ms}, {end_ms}, and {interval}."
        ),
    )
    parser.add_argument(
        "--report-type",
        choices=tuple(sorted(REPORT_ENDPOINTS)),
        default=os.getenv("ALKIRA_REPORT_TYPE", DEFAULT_REPORT_TYPE),
        help="Built-in Alkira dashboard stats report to pull when --endpoint is not set.",
    )
    parser.add_argument(
        "--start",
        type=parse_datetime,
        help=(
            "Report start time as YYYY-MM-DD or ISO-8601. Defaults to 24 hours ago, "
            "or 2026-06-01T00:00:00-04:00 when --budget-remaining is used."
        ),
    )
    parser.add_argument(
        "--end",
        type=parse_datetime,
        help="Report end time as YYYY-MM-DD or ISO-8601. Defaults to now.",
    )
    parser.add_argument(
        "--time-format",
        choices=("epoch-seconds", "epoch-ms", "iso"),
        default=os.getenv("ALKIRA_TIME_FORMAT", "epoch-seconds"),
        help="Format used for start/end query parameters.",
    )
    parser.add_argument(
        "--period",
        default=os.getenv("ALKIRA_PERIOD"),
        help="Optional Alkira dashboard period value such as 2hours, 24hours, or custom.",
    )
    parser.add_argument(
        "--cxp",
        default=os.getenv("ALKIRA_CXP"),
        help="CXP name to pass as a query filter, for example USEAST-AZURE-2.",
    )
    parser.add_argument(
        "--segment",
        default=os.getenv("ALKIRA_SEGMENT"),
        help="Segment name to pass as a query filter, for example 'PVH CORP'.",
    )
    parser.add_argument(
        "--max-items",
        default=os.getenv("ALKIRA_MAX_ITEMS"),
        help="Optional dashboard maxItems query parameter.",
    )
    parser.add_argument(
        "--traffic-bandwidth-type",
        choices=("MAX", "AVG"),
        default=os.getenv("ALKIRA_TRAFFIC_BANDWIDTH_TYPE"),
        help="Optional dashboard trafficBandwidthType query parameter.",
    )
    parser.add_argument(
        "--interval",
        default=os.getenv("ALKIRA_INTERVAL"),
        help="Dashboard stats interval, in seconds. Defaults to 300 for chart-style reports.",
    )
    parser.add_argument(
        "--granularity",
        help="Optional legacy/custom granularity value for tenant-specific endpoints.",
    )
    parser.add_argument("--start-param", default="startTime")
    parser.add_argument("--end-param", default="endTime")
    parser.add_argument("--interval-param", default="interval")
    parser.add_argument("--granularity-param", default="granularity")
    parser.add_argument(
        "--param",
        action="append",
        help="Extra query parameter as KEY=VALUE. Can be repeated.",
    )
    parser.add_argument(
        "--format",
        choices=("auto", "json", "csv", "raw"),
        default="auto",
        help="Output format. CSV flattens JSON responses.",
    )
    parser.add_argument(
        "--output-unit",
        type=parse_output_unit,
        default=os.getenv("ALKIRA_OUTPUT_UNIT", "auto"),
        help=(
            "Unit for RX/TX display, CSV unit columns, and budget summary. "
            "Use auto, bytes, gigabytes/gb, or terabytes/tb. "
            "'terrabytes' is accepted as an alias."
        ),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--delivery-config",
        type=Path,
        default=(
            Path(os.getenv("ALKIRA_REPORT_DELIVERY_CONFIG"))
            if os.getenv("ALKIRA_REPORT_DELIVERY_CONFIG")
            else None
        ),
        help="JSON config for email and Teams delivery settings.",
    )
    parser.add_argument(
        "--send-email",
        action="store_true",
        help="Email the completed report using the email section in --delivery-config.",
    )
    parser.add_argument(
        "--send-teams",
        action="store_true",
        help="Post a report summary to Teams using the teams section in --delivery-config.",
    )
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--verbose", action="store_true")
    return parser


def run(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.examples:
        print(EXAMPLES.rstrip())
        return 0

    if not args.portal:
        parser.error("--portal or ALKIRA_PORTAL is required")
    if args.report_type not in REPORT_ENDPOINTS:
        parser.error(
            "--report-type must be one of: "
            + ", ".join(sorted(REPORT_ENDPOINTS))
        )
    if args.budget_remaining and args.budget_total_tb <= 0:
        parser.error("--budget-total-tb must be greater than 0")
    if args.report_type == "connector-data" and not args.endpoint and not args.connector_id:
        parser.error("--connector-id is required for --report-type connector-data")
    if (args.send_email or args.send_teams) and not args.delivery_config:
        parser.error("--delivery-config is required with --send-email or --send-teams")

    try:
        delivery_config = load_delivery_config(args.delivery_config)
    except AlkiraError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    if args.budget_remaining and not args.period:
        args.period = "custom"
    start, end = resolve_time_range(args, now)
    if start >= end:
        parser.error("--start must be earlier than --end")

    client = AlkiraClient(
        portal=args.portal,
        api_key=args.api_key,
        username=args.username,
        password=args.password,
        timeout=args.timeout,
        verbose=args.verbose,
    )

    budget_details: Optional[dict[str, Any]] = None
    try:
        client.authenticate()
        tenant_network_id = args.tenant_network_id or client.tenant_network_id()
        context = {
            "tenant_network_id": tenant_network_id,
            "connector_id": args.connector_id or "",
            "start": iso_z(start),
            "end": iso_z(end),
            "start_epoch": epoch_seconds(start),
            "end_epoch": epoch_seconds(end),
            "start_ms": epoch_milliseconds(start),
            "end_ms": epoch_milliseconds(end),
            "interval": args.interval or "",
            "granularity": args.granularity or "",
        }
        query = build_query(args, start, end, args.report_type)
        default_endpoints = list(REPORT_ENDPOINTS[args.report_type])
        endpoints = [endpoint for endpoint in (args.endpoint or default_endpoints) if endpoint]
        endpoint, response = choose_report_endpoint(client, endpoints, context, query)
        if args.budget_remaining:
            budget_details = budget_remaining_details(
                response,
                budget_total_tb=args.budget_total_tb,
                field=args.budget_field,
                output_unit=args.output_unit,
            )

        output_format = resolve_output_format(args.format, response)
        output_path = args.output or default_output_path(
            "json" if output_format == "raw" else output_format, start, end
        )

        row_count: Optional[int] = None
        if output_format == "json":
            write_json(output_path, response)
        elif output_format == "csv":
            row_count = write_csv(
                output_path,
                response,
                args.output_unit,
                budget_details,
            )
        else:
            write_raw(output_path, response)

    except AlkiraError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    details = f"Pulled Alkira {args.report_type} report from {endpoint}"
    if row_count is not None:
        details += f" ({row_count} CSV row{'s' if row_count != 1 else ''})"
    summary = traffic_summary(response, args.output_unit)
    if summary:
        details += f"\nSummary: {summary}"
    if args.budget_remaining:
        details += f"\nBudget Window: {iso_z(start)} to {iso_z(end)}"
        if budget_details:
            details += (
                "\nBudget Remaining: "
                f"{budget_remaining_summary_from_details(budget_details)}"
            )
        else:
            details += "\nBudget Remaining: No TX/RX data found in response."

    delivery_results = []
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
    except AlkiraError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for result in delivery_results:
        details += f"\nDelivery: {result}"

    print(f"{details}\nWrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
