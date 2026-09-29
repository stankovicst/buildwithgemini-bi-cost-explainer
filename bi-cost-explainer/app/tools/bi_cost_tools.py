"""Firestore function tools for querying and analyzing BI costs."""

import json
import urllib.request
from typing import Any
from google.cloud import firestore

PROJECT_ID = "qwiklabs-gcp-03-6baaeaff7c42"
COLLECTION_NAME = "bi_costs"

# Initialize Firestore client with hardcoded project ID
_db = firestore.Client(project=PROJECT_ID)


def list_available_weeks() -> list[str]:
    """Retrieves all distinct available week_start dates from bi_costs in chronological order."""
    docs = _db.collection(COLLECTION_NAME).stream()
    weeks = {doc.to_dict().get("week_start") for doc in docs if doc.to_dict().get("week_start")}
    return sorted(list(weeks))


def get_costs(
    team: str | None = None,
    tool: str | None = None,
    start_week: str | None = None,
    end_week: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieves filtered BI cost records from Firestore.

    Args:
        team: Optional team name ('Sales', 'Supply Chain', 'Finance', 'Marketing').
        tool: Optional tool name ('Looker', 'Looker Studio', 'Tableau').
        start_week: Optional inclusive start week ISO date (e.g. '2026-09-07').
        end_week: Optional inclusive end week ISO date (e.g. '2026-09-14').

    Returns:
        List of matching cost records.
    """
    docs = _db.collection(COLLECTION_NAME).stream()
    records = []
    for doc in docs:
        data = doc.to_dict()
        if team and data.get("team") != team:
            continue
        if tool and data.get("tool") != tool:
            continue
        if start_week and data.get("week_start", "") < start_week:
            continue
        if end_week and data.get("week_start", "") > end_week:
            continue
        records.append(data)

    records.sort(key=lambda r: (r.get("week_start", ""), r.get("cost_usd", 0.0)), reverse=True)
    return records


def compare_periods(
    week_a: str,
    week_b: str,
    group_by: str = "team,tool",
) -> list[dict[str, Any]]:
    """Compares BI costs between two weeks (week_a as baseline, week_b as target).

    Args:
        week_a: Baseline week ISO date string (e.g. '2026-09-07').
        week_b: Target week ISO date string (e.g. '2026-09-14').
        group_by: Grouping key ('team,tool', 'team', or 'tool'). Default is 'team,tool'.

    Returns:
        A list of grouped records with cost delta, query count delta, gb processed delta,
        and percentage changes, sorted by absolute cost change descending.
    """
    records_a = get_costs(start_week=week_a, end_week=week_a)
    records_b = get_costs(start_week=week_b, end_week=week_b)

    def get_group_key(r: dict[str, Any]) -> str:
        if group_by == "team":
            return r.get("team", "")
        if group_by == "tool":
            return r.get("tool", "")
        return f"{r.get('team', '')} - {r.get('tool', '')}"

    grouped: dict[str, dict[str, Any]] = {}

    for r in records_a:
        key = get_group_key(r)
        entry = grouped.setdefault(key, {
            "group": key,
            "team": r.get("team"),
            "tool": r.get("tool"),
            "cost_week_a": 0.0,
            "cost_week_b": 0.0,
            "gb_week_a": 0.0,
            "gb_week_b": 0.0,
            "queries_week_a": 0,
            "queries_week_b": 0,
            "top_dashboard_a": r.get("top_dashboard"),
            "top_dashboard_b": "",
        })
        entry["cost_week_a"] = round(entry["cost_week_a"] + r.get("cost_usd", 0.0), 2)
        entry["gb_week_a"] = round(entry["gb_week_a"] + r.get("gb_processed", 0.0), 2)
        entry["queries_week_a"] += r.get("query_count", 0)

    for r in records_b:
        key = get_group_key(r)
        entry = grouped.setdefault(key, {
            "group": key,
            "team": r.get("team"),
            "tool": r.get("tool"),
            "cost_week_a": 0.0,
            "cost_week_b": 0.0,
            "gb_week_a": 0.0,
            "gb_week_b": 0.0,
            "queries_week_a": 0,
            "queries_week_b": 0,
            "top_dashboard_a": "",
            "top_dashboard_b": r.get("top_dashboard"),
        })
        entry["cost_week_b"] = round(entry["cost_week_b"] + r.get("cost_usd", 0.0), 2)
        entry["gb_week_b"] = round(entry["gb_week_b"] + r.get("gb_processed", 0.0), 2)
        entry["queries_week_b"] += r.get("query_count", 0)
        entry["top_dashboard_b"] = r.get("top_dashboard")

    results = []
    for entry in grouped.values():
        c_a = entry["cost_week_a"]
        c_b = entry["cost_week_b"]
        gb_a = entry["gb_week_a"]
        gb_b = entry["gb_week_b"]
        q_a = entry["queries_week_a"]
        q_b = entry["queries_week_b"]

        cost_delta = round(c_b - c_a, 2)
        gb_delta = round(gb_b - gb_a, 2)
        queries_delta = q_b - q_a

        pct_cost_change = round((cost_delta / c_a) * 100, 2) if c_a > 0 else 0.0
        pct_gb_change = round((gb_delta / gb_a) * 100, 2) if gb_a > 0 else 0.0
        pct_queries_change = round((queries_delta / q_a) * 100, 2) if q_a > 0 else 0.0

        results.append({
            "group": entry["group"],
            "team": entry["team"],
            "tool": entry["tool"],
            "top_dashboard": entry["top_dashboard_b"] or entry["top_dashboard_a"],
            "cost_week_a": c_a,
            "cost_week_b": c_b,
            "cost_delta": cost_delta,
            "pct_cost_change": pct_cost_change,
            "gb_week_a": gb_a,
            "gb_week_b": gb_b,
            "gb_delta": gb_delta,
            "pct_gb_change": pct_gb_change,
            "queries_week_a": q_a,
            "queries_week_b": q_b,
            "queries_delta": queries_delta,
            "pct_queries_change": pct_queries_change,
        })

    # Sorted by absolute cost change
    results.sort(key=lambda x: abs(x["cost_delta"]), reverse=True)
    return results


def suggest_fix(query_count_change: float, gb_processed_change: float) -> str:
    """Provides deterministic remediation guidance based on changes in queries and data scanned.

    Deterministic rules:
    - gb up + queries flat -> "full scans: add partition filter or use an extract"
    - queries up + cost flat -> "usage growth, efficient — no action"
    - both up -> "more users on an expensive dashboard: schedule instead of live"

    Args:
        query_count_change: Change in query count (either percentage like -0.5% or raw delta).
        gb_processed_change: Change in GB processed (either percentage like +227.2% or raw delta).

    Returns:
        A deterministic remediation string.
    """
    # Handle raw volume deltas if large numbers are provided
    if abs(gb_processed_change) > 500 or abs(query_count_change) > 500:
        if gb_processed_change > 1000 and query_count_change > 500:
            return "more users on an expensive dashboard: schedule instead of live"
        if gb_processed_change > 1000 and abs(query_count_change) <= 500:
            return "full scans: add partition filter or use an extract"
        if query_count_change > 500 and abs(gb_processed_change) <= 1000:
            return "usage growth, efficient — no action"
        return "usage is within normal variance — no action needed"

    # Percentage / relative changes
    if gb_processed_change > 15.0 and query_count_change > 15.0:
        return "more users on an expensive dashboard: schedule instead of live"
    if gb_processed_change > 15.0 and abs(query_count_change) <= 12.0:
        return "full scans: add partition filter or use an extract"
    if query_count_change > 15.0 and abs(gb_processed_change) <= 12.0:
        return "usage growth, efficient — no action"
    return "usage is within normal variance — no action needed"


def convert_currency(
    amount: float,
    from_currency: str = "USD",
    to_currency: str = "EUR",
) -> dict[str, Any]:
    """Converts a currency amount using latest exchange rates from the Frankfurter API.

    Args:
        amount: Numerical amount to convert.
        from_currency: Base 3-letter currency code (default: 'USD').
        to_currency: Target 3-letter currency code (default: 'EUR').

    Returns:
        Dictionary with converted amount and rate date.
    """
    url = f"https://api.frankfurter.dev/v1/latest?base={from_currency}&symbols={to_currency}"
    req = urllib.request.Request(url, headers={"User-Agent": "bi-cost-explainer"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    rate = data["rates"][to_currency]
    return {
        "original_amount": amount,
        "from_currency": from_currency,
        "converted_amount": round(amount * rate, 2),
        "to_currency": to_currency,
        "rate_date": data.get("date"),
    }

