#!/usr/bin/env python3
"""
uptime_report.py: Check the public status pages of SaaS tools a company
depends on, then write a short Markdown summary: what is up right now,
what incidents are open, and uptime percentage across past runs.

Why: when users report "Slack is broken," the first question is whether
it is us or the vendor. Running this on a schedule also builds a simple
uptime history for monthly reporting.

Usage:
  python3 scripts/uptime_report.py
  python3 scripts/uptime_report.py --config config/status_pages.json --out output/
  python3 scripts/uptime_report.py --no-history     # check only, do not record this run

Each run appends one row per service to <out>/uptime_history.csv and
writes <out>/uptime-report.md. Both are git-ignored.

Exit codes: 0 = every service operational, 1 = at least one is not, 2 = could not run.

Supported status page formats:
  - "statuspage": Atlassian Statuspage, used by GitHub, Cloudflare, Atlassian, and many others.
                  Endpoint: https://<status-site>/api/v2/summary.json
  - "slack":      Slack's own status API. Endpoint: https://slack-status.com/api/v2.0.0/current
Uses only the Python standard library.
"""

import argparse
import csv
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

OPERATIONAL = "operational"
MAX_COMPONENTS_LISTED = 3

# Statuspage reports an overall "indicator". Map it to plain words.
STATUSPAGE_INDICATORS = {
    "none": OPERATIONAL,
    "minor": "degraded",
    "major": "outage",
    "critical": "outage",
    "maintenance": "maintenance",
}


def parse_statuspage(data):
    """Turn an Atlassian Statuspage summary.json into (state, notes)."""
    state = STATUSPAGE_INDICATORS.get(data.get("status", {}).get("indicator"), "unknown")
    notes = [incident["name"] for incident in data.get("incidents", [])
             if incident.get("status") != "resolved"]
    # Also name the specific parts that are down, e.g. "Actions: partial outage".
    # Some vendors (Cloudflare) list every data center as a component, so only
    # the first few are named to keep the report readable.
    affected = [f"{c['name']}: {c['status'].replace('_', ' ')}"
                for c in data.get("components", [])
                if c.get("status") not in (OPERATIONAL, None) and not c.get("group")]
    notes += affected[:MAX_COMPONENTS_LISTED]
    if len(affected) > MAX_COMPONENTS_LISTED:
        notes.append(f"and {len(affected) - MAX_COMPONENTS_LISTED} more components affected")
    return state, notes


def parse_slack(data):
    """Turn Slack's status API response into (state, notes)."""
    incidents = data.get("active_incidents", [])
    if data.get("status") == "ok" and not incidents:
        return OPERATIONAL, []
    # Slack labels each incident as "incident", "outage", or "notice".
    types = {incident.get("type") for incident in incidents}
    state = "outage" if "outage" in types else "degraded"
    return state, [incident.get("title", "untitled incident") for incident in incidents]


PARSERS = {"statuspage": parse_statuspage, "slack": parse_slack}


def fetch_json(url, timeout=10):
    request = urllib.request.Request(url, headers={"User-Agent": "uptime-report/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def check_service(service, fetch=fetch_json):
    """
    Check one service. Never raises: if the status page itself cannot be
    reached, the state is "unknown" and the error is kept as a note.
    `fetch` is a parameter so tests can pass in fake data.
    """
    try:
        state, notes = PARSERS[service["kind"]](fetch(service["url"]))
    except Exception as error:  # noqa: BLE001 (one bad page must not stop the report)
        state, notes = "unknown", [f"could not read status page ({error.__class__.__name__})"]
    return {"name": service["name"], "state": state, "notes": notes}


def append_history(path, results, checked_at):
    new_file = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if new_file:
            writer.writerow(["checked_at", "service", "state"])
        for result in results:
            writer.writerow([checked_at, result["name"], result["state"]])


def uptime_from_history(path):
    """
    Return {service: (percent_operational, number_of_checks)}.
    "unknown" rows (status page unreachable) are skipped, since they say
    nothing about whether the service itself was up.
    """
    totals = {}
    if not os.path.exists(path):
        return {}
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["state"] == "unknown":
                continue
            up, count = totals.get(row["service"], (0, 0))
            totals[row["service"]] = (up + (row["state"] == OPERATIONAL), count + 1)
    return {name: (100.0 * up / count, count) for name, (up, count) in totals.items()}


def build_report(results, uptime, checked_at):
    """Return the Markdown report as a string."""
    down = [r for r in results if r["state"] != OPERATIONAL]
    headline = ("All monitored services are operational." if not down
                else f"{len(down)} of {len(results)} services need attention: "
                     + ", ".join(r["name"] for r in down) + ".")

    lines = [
        "# SaaS Status Report",
        "",
        f"Checked: {checked_at}",
        "",
        f"**{headline}**",
        "",
        "| Service | Status now | Uptime (recorded checks) | Notes |",
        "|---|---|---|---|",
    ]
    for result in results:
        if result["name"] in uptime:
            percent, count = uptime[result["name"]]
            uptime_text = f"{percent:.1f}% of {count}"
        else:
            uptime_text = "no history yet"
        # A "|" inside a cell would end the cell early and break the table.
        notes = "; ".join(result["notes"]).replace("|", "\\|") or "-"
        lines.append(f"| {result['name']} | {result['state']} | {uptime_text} | {notes} |")

    lines += [
        "",
        "Uptime here is the share of this script's own checks that found the service",
        "operational. It is a rough trend, not the vendor's official SLA number.",
    ]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Summarize SaaS status pages.")
    parser.add_argument("--config", default="config/status_pages.json")
    parser.add_argument("--out", default="output")
    parser.add_argument("--no-history", action="store_true", help="do not record this run")
    args = parser.parse_args(argv)

    try:
        with open(args.config, encoding="utf-8") as handle:
            services = json.load(handle)["services"]
        os.makedirs(args.out, exist_ok=True)
    except (OSError, ValueError, KeyError) as error:
        print(f"Could not run: {error}", file=sys.stderr)
        return 2

    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    results = [check_service(service) for service in services]

    history_path = os.path.join(args.out, "uptime_history.csv")
    if not args.no_history:
        append_history(history_path, results, checked_at)

    report = build_report(results, uptime_from_history(history_path), checked_at)
    with open(os.path.join(args.out, "uptime-report.md"), "w", encoding="utf-8") as handle:
        handle.write(report)
    print(report)

    return 0 if all(r["state"] == OPERATIONAL for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
