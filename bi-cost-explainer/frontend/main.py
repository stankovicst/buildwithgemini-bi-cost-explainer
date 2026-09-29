"""FastAPI proxy and BI Cost Analytics API for deployed ADK agent."""

import json
import os
import time
import uuid
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import google.auth
import google.auth.transport.requests
from google.cloud import firestore
import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.types import (
    AgentCard,
    FilePart,
    Message,
    Part,
    Role,
    TaskArtifactUpdateEvent,
    TextPart,
    TransportProtocol,
)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# --- Configuration & GCP Clients ---
PROJECT_ID = "qwiklabs-gcp-03-6baaeaff7c42"
COLLECTION_NAME = "bi_costs"

RESOURCE = os.environ.get(
    "AGENT_ENGINE_RESOURCE_NAME",
    "projects/383698302461/locations/us-east1/reasoningEngines/6689197845947351040",
)
AGENT_DIRECTORY = os.environ.get("AGENT_DIRECTORY", "app")
LOCATION = RESOURCE.split("/locations/")[1].split("/")[0]

A2A_BASE = (
    f"https://{LOCATION}-aiplatform.googleapis.com/reasoningEngines/v1/"
    f"{RESOURCE}/api/a2a/{AGENT_DIRECTORY}"
)
A2A_CARD_URL = f"{A2A_BASE}/.well-known/agent-card.json"
_A2UI_MIME = "application/json+a2ui"

# Authenticated clients
_creds, _ = google.auth.default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)
_db = firestore.Client(project=PROJECT_ID)

# In-memory caches
_records_cache = {"timestamp": 0, "records": []}
_fx_cache = {"timestamp": 0, "rate": 0.88, "date": "2026-09-29"}


def _auth_headers() -> dict[str, str]:
    _creds.refresh(google.auth.transport.requests.Request())
    return {
        "Authorization": f"Bearer {_creds.token}",
        "Content-Type": "application/json",
    }


def get_all_records() -> list[dict[str, Any]]:
    """Stream all bi_costs records with a short 30-second cache for instant dashboard loads."""
    now = time.time()
    if now - _records_cache["timestamp"] < 30 and _records_cache["records"]:
        return _records_cache["records"]
    docs = _db.collection(COLLECTION_NAME).stream()
    records = [d.to_dict() for d in docs]
    _records_cache["records"] = records
    _records_cache["timestamp"] = now
    return records


def suggest_fix(query_count_change: float, gb_processed_change: float) -> str:
    """Matches the exact remediation logic in app/tools/bi_cost_tools.py."""
    if gb_processed_change > 15.0 and query_count_change > 15.0:
        return "more users on an expensive dashboard: schedule instead of live"
    if gb_processed_change > 15.0 and abs(query_count_change) <= 12.0:
        return "full scans: add partition filter or use an extract"
    if query_count_change > 15.0 and abs(gb_processed_change) <= 12.0:
        return "usage growth, efficient — no action"
    return "usage is within normal variance — no action needed"


async def get_fx_rate() -> dict[str, Any]:
    """USD to EUR exchange rate with 1-hour cache."""
    now = time.time()
    if now - _fx_cache["timestamp"] < 3600 and _fx_cache["timestamp"] > 0:
        return {"base": "USD", "target": "EUR", "rate": _fx_cache["rate"], "date": _fx_cache["date"]}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                "https://api.frankfurter.dev/v1/latest?base=USD&symbols=EUR",
                headers={"User-Agent": "bi-cost-explainer"},
            )
            if resp.status_code == 200:
                data = resp.json()
                _fx_cache["rate"] = float(data["rates"]["EUR"])
                _fx_cache["date"] = data.get("date", "")
                _fx_cache["timestamp"] = now
    except Exception as e:
        print(f"FX fetch warning: {e}")
    return {"base": "USD", "target": "EUR", "rate": _fx_cache["rate"], "date": _fx_cache["date"]}


app = FastAPI(title="BI Cost Explainer Dashboard & Chat")


@app.exception_handler(Exception)
async def _json_errors(request: Request, exc: Exception):
    return JSONResponse(
        status_code=200,
        content={"parts": [{"kind": "text", "text": f"Error: {type(exc).__name__}: {exc}"}]},
    )


# --- Analytics & Data Endpoints ---

@app.get("/api/fx")
async def api_fx():
    return await get_fx_rate()


@app.get("/api/summary")
def api_summary(week: str | None = None):
    records = get_all_records()
    if not records:
        return {"error": "No records in Firestore"}

    weeks = sorted(list({r["week_start"] for r in records if r.get("week_start")}))
    if not weeks:
        return {"error": "No weekly data found"}

    selected_week = week if (week and week in weeks) else weeks[-1]
    sel_idx = weeks.index(selected_week)
    prev_week = weeks[sel_idx - 1] if sel_idx > 0 else None

    w_curr = [r for r in records if r.get("week_start") == selected_week]
    w_prev = [r for r in records if r.get("week_start") == prev_week] if prev_week else []

    total_cost = round(sum(r.get("cost_usd", 0.0) for r in w_curr), 2)
    prev_cost = round(sum(r.get("cost_usd", 0.0) for r in w_prev), 2) if w_prev else 0.0
    cost_delta = round(total_cost - prev_cost, 2)
    cost_delta_pct = round((cost_delta / prev_cost) * 100, 2) if prev_cost > 0 else 0.0

    total_gb = round(sum(r.get("gb_processed", 0.0) for r in w_curr), 1)
    prev_gb = round(sum(r.get("gb_processed", 0.0) for r in w_prev), 1) if w_prev else 0.0
    gb_delta = round(total_gb - prev_gb, 1)
    gb_delta_pct = round((gb_delta / prev_gb) * 100, 2) if prev_gb > 0 else 0.0

    total_queries = sum(r.get("query_count", 0) for r in w_curr)
    prev_queries = sum(r.get("query_count", 0) for r in w_prev) if w_prev else 0
    queries_delta = total_queries - prev_queries
    queries_delta_pct = round((queries_delta / prev_queries) * 100, 2) if prev_queries > 0 else 0.0

    # Sparklines for all weeks
    spark_cost = []
    spark_gb = []
    spark_queries = []
    for w in weeks:
        w_docs = [r for r in records if r.get("week_start") == w]
        spark_cost.append(round(sum(r.get("cost_usd", 0.0) for r in w_docs), 2))
        spark_gb.append(round(sum(r.get("gb_processed", 0.0) for r in w_docs), 1))
        spark_queries.append(sum(r.get("query_count", 0) for r in w_docs))

    return {
        "selected_week": selected_week,
        "previous_week": prev_week,
        "available_weeks": weeks,
        "total_cost": total_cost,
        "prev_cost": prev_cost,
        "cost_delta": cost_delta,
        "cost_delta_pct": cost_delta_pct,
        "total_gb": total_gb,
        "prev_gb": prev_gb,
        "gb_delta": gb_delta,
        "gb_delta_pct": gb_delta_pct,
        "total_queries": total_queries,
        "prev_queries": prev_queries,
        "queries_delta": queries_delta,
        "queries_delta_pct": queries_delta_pct,
        "sparklines": {
            "weeks": weeks,
            "cost": spark_cost,
            "gb": spark_gb,
            "queries": spark_queries,
        },
    }


@app.get("/api/timeseries")
def api_timeseries():
    records = get_all_records()
    weeks = sorted(list({r["week_start"] for r in records if r.get("week_start")}))
    tools = sorted(list({r["tool"] for r in records if r.get("tool")}))
    teams = sorted(list({r["team"] for r in records if r.get("team")}))

    by_tool: dict[str, list[float]] = {t: [] for t in tools}
    by_team: dict[str, list[float]] = {t: [] for t in teams}

    for w in weeks:
        w_records = [r for r in records if r.get("week_start") == w]
        for t in tools:
            cost = sum(r.get("cost_usd", 0.0) for r in w_records if r.get("tool") == t)
            by_tool[t].append(round(cost, 2))
        for tm in teams:
            cost = sum(r.get("cost_usd", 0.0) for r in w_records if r.get("team") == tm)
            by_team[tm].append(round(cost, 2))

    return {
        "weeks": weeks,
        "tools": tools,
        "teams": teams,
        "by_tool": by_tool,
        "by_team": by_team,
    }


@app.get("/api/drivers")
def api_drivers(week: str | None = None):
    records = get_all_records()
    weeks = sorted(list({r["week_start"] for r in records if r.get("week_start")}))
    selected_week = week if (week and week in weeks) else weeks[-1]
    sel_idx = weeks.index(selected_week)
    prev_week = weeks[sel_idx - 1] if sel_idx > 0 else None

    w_curr = [r for r in records if r.get("week_start") == selected_week]
    w_prev = [r for r in records if r.get("week_start") == prev_week] if prev_week else []

    drivers = []
    for curr in w_curr:
        team = curr.get("team")
        tool = curr.get("tool")
        prev = next((p for p in w_prev if p.get("team") == team and p.get("tool") == tool), None)

        c_now = float(curr.get("cost_usd", 0.0))
        c_prev = float(prev.get("cost_usd", 0.0)) if prev else 0.0
        c_delta = round(c_now - c_prev, 2)
        c_pct = round((c_delta / c_prev) * 100, 2) if c_prev > 0 else 0.0

        gb_now = float(curr.get("gb_processed", 0.0))
        gb_prev = float(prev.get("gb_processed", 0.0)) if prev else 0.0
        gb_delta = round(gb_now - gb_prev, 2)
        gb_pct = round((gb_delta / gb_prev) * 100, 2) if gb_prev > 0 else 0.0

        q_now = int(curr.get("query_count", 0))
        q_prev = int(prev.get("query_count", 0)) if prev else 0
        q_delta = q_now - q_prev
        q_pct = round((q_delta / q_prev) * 100, 2) if q_prev > 0 else 0.0

        fix_label = suggest_fix(q_pct, gb_pct)

        drivers.append({
            "team": team,
            "tool": tool,
            "group": f"{team} - {tool}",
            "top_dashboard": curr.get("top_dashboard", ""),
            "cost": c_now,
            "cost_prev": c_prev,
            "cost_delta": c_delta,
            "cost_delta_pct": c_pct,
            "gb": gb_now,
            "gb_prev": gb_prev,
            "gb_delta": gb_delta,
            "gb_delta_pct": gb_pct,
            "queries": q_now,
            "queries_prev": q_prev,
            "queries_delta": q_delta,
            "queries_delta_pct": q_pct,
            "fix_label": fix_label,
        })

    # Sort drivers by absolute cost delta descending
    drivers.sort(key=lambda d: abs(d["cost_delta"]), reverse=True)

    # Compute insights on start
    top_driver = max(drivers, key=lambda d: d["cost_delta"], default=None)
    # Red herring: highest query increase with flat/low spend increase
    red_herring_candidates = [
        d for d in drivers
        if d["fix_label"] == "usage growth, efficient — no action"
        or (d["queries_delta_pct"] > 15.0 and d["cost_delta_pct"] < 15.0)
    ]
    red_herring = max(red_herring_candidates, key=lambda d: d["queries_delta_pct"], default=None)
    if not red_herring and drivers:
        red_herring = max(drivers, key=lambda d: d["queries_delta_pct"])

    return {
        "selected_week": selected_week,
        "previous_week": prev_week,
        "drivers": drivers,
        "insights": {
            "top_driver": top_driver,
            "red_herring": red_herring,
        },
    }


# --- Agent Chat Proxy (A2A Protocol) ---

_contexts: dict[str, str] = {}
_card: AgentCard | None = None


async def _get_card(client: httpx.AsyncClient) -> AgentCard:
    global _card
    if _card is None:
        resp = await client.get(A2A_CARD_URL)
        resp.raise_for_status()
        card = AgentCard(**resp.json())
        card.url = A2A_BASE
        _card = card
    return _card


def _extract_parts(parts: list) -> list[dict]:
    out: list[dict] = []
    for p in parts:
        root = getattr(p, "root", p)
        if isinstance(root, TextPart) and getattr(root, "text", None):
            out.append({"kind": "text", "text": root.text})
        elif getattr(root, "text", None):
            out.append({"kind": "text", "text": root.text})
        elif getattr(root, "data", None) is not None:
            raw_data = root.data
            meta = getattr(root, "metadata", None) or {}
            if isinstance(raw_data, dict):
                inner_meta = raw_data.get("metadata") or {}
                mime = (
                    meta.get("mimeType")
                    or (inner_meta.get("mimeType") if isinstance(inner_meta, dict) else None)
                )
                if mime == _A2UI_MIME:
                    a2ui_msg = raw_data.get("data", raw_data)
                    if isinstance(a2ui_msg, str):
                        try:
                            a2ui_msg = json.loads(a2ui_msg)
                        except Exception:
                            pass
                    out.append({"kind": "a2ui", "data": a2ui_msg})
                elif "beginRendering" in raw_data or "surfaceUpdate" in raw_data:
                    out.append({"kind": "a2ui", "data": raw_data})
                elif isinstance(raw_data.get("data"), dict) and (
                    "beginRendering" in raw_data["data"] or "surfaceUpdate" in raw_data["data"]
                ):
                    out.append({"kind": "a2ui", "data": raw_data["data"]})
        elif isinstance(root, FilePart):
            uri = getattr(getattr(root, "file", None), "uri", None)
            if uri:
                out.append({"kind": "text", "text": uri})
    return out


@app.post("/chat")
async def chat(req: Request):
    body = await req.json()
    message = body.get("message", "")
    user_id = body.get("user_id") or "web-user"
    parts: list[dict] = []

    async with httpx.AsyncClient(headers=_auth_headers(), timeout=180) as client:
        card = await _get_card(client)
        factory = ClientFactory(
            ClientConfig(
                supported_transports=[
                    TransportProtocol.jsonrpc,
                    TransportProtocol.http_json,
                ],
                httpx_client=client,
            )
        )
        a2a_client = factory.create(card)

        msg = Message(
            message_id=str(uuid.uuid4()),
            role=Role.user,
            parts=[Part(root=TextPart(text=message))],
            context_id=_contexts.get(user_id),
        )

        last_task = None
        async for event in a2a_client.send_message(msg):
            if not isinstance(event, tuple):
                continue
            task, update = event
            if task is not None:
                last_task = task
                if getattr(task, "context_id", None):
                    _contexts[user_id] = task.context_id
            if isinstance(update, TaskArtifactUpdateEvent):
                parts.extend(_extract_parts(update.artifact.parts))

        if not parts and last_task is not None:
            for artifact in getattr(last_task, "artifacts", None) or []:
                parts.extend(_extract_parts(artifact.parts))

        if not parts and last_task is not None:
            for m in reversed(getattr(last_task, "history", None) or []):
                if getattr(m, "role", None) in (Role.agent, "agent"):
                    extracted = _extract_parts(getattr(m, "parts", []))
                    if extracted:
                        parts.extend(extracted)
                        break

    if not parts:
        parts = [{"kind": "text", "text": "(The agent didn't return a reply.)"}]
    return JSONResponse({"parts": parts})


STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
