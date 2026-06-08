"""
api_server.py — Livetime REST API
===================================
Thin HTTP wrapper around the SQLite helpers.
Runs alongside (or instead of) mcp_server.py so the frontend can
call it via Fetch API.

    pip install fastapi uvicorn[standard]
    python api_server.py            # default :8080
    python api_server.py --port 3001

CORS is open so GitHub Pages (or any origin) can reach a local/ngrok server.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# re-use the same DB helpers from agent.py
sys.path.insert(0, str(Path(__file__).parent))
from agent import (
    _fetch_events,
    _fetch_mood_series,
    _fetch_skills,
    _get_summary_stats,
    build_analyze_context,
    build_export_context,
    LivetimeAgent,
)
from seed import get_conn

# ── app setup ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="Livetime API",
    description="REST interface for the Livetime 時光機 timeline database",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten in production
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_agent: LivetimeAgent | None = None

def get_agent() -> LivetimeAgent:
    global _agent
    if _agent is None:
        _agent = LivetimeAgent()
    return _agent


# ── events ─────────────────────────────────────────────────────────────────

@app.get("/api/events")
def list_events(
    year:     Optional[int] = None,
    category: Optional[str] = None,
    momentum: Optional[str] = None,
    tag:      Optional[str] = None,
    limit:    int            = 50,
    offset:   int            = 0,
):
    """List timeline events with optional filters."""
    return _fetch_events(
        year=year, category=category, momentum=momentum,
        tag=tag, limit=min(int(limit), 200), offset=int(offset),
    )


@app.get("/api/events/{event_id}")
def get_event(event_id: str):
    """Get a single event by ID (e.g. 'e1')."""
    conn = get_conn()
    row = conn.execute(
        """SELECT e.*, et.label AS type_label, et.icon AS type_icon,
                  m.label AS momentum_label, m.color AS momentum_color, m.icon AS momentum_icon
           FROM events e
           LEFT JOIN event_types    et ON et.key = e.type
           LEFT JOIN momentum_types m  ON m.key  = e.momentum
           WHERE e.id = ?""",
        (event_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Event '{event_id}' not found")
    ev = dict(row)
    tag_rows = conn.execute(
        "SELECT t.name FROM tags t JOIN event_tags et ON et.tag_id=t.id WHERE et.event_id=?",
        (event_id,),
    ).fetchall()
    ev["tags"] = [r["name"] for r in tag_rows]
    ev["has_media"] = bool(ev["has_media"])
    conn.close()
    return ev


@app.get("/api/search")
def search(q: str, limit: int = 20):
    """Full-text search across event titles, descriptions, and tags."""
    conn = get_conn()
    like = f"%{q}%"
    rows = conn.execute(
        """SELECT DISTINCT e.id, e.title, e.date_label, e.type, e.momentum, e.description
           FROM events e
           LEFT JOIN event_tags et ON et.event_id=e.id
           LEFT JOIN tags t        ON t.id=et.tag_id
           WHERE e.title LIKE ? OR e.description LIKE ? OR t.name LIKE ?
           ORDER BY e.date_sort DESC LIMIT ?""",
        (like, like, like, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── supporting data ────────────────────────────────────────────────────────

@app.get("/api/mood-series")
def mood_series(
    from_yyyymm: Optional[int] = None,
    to_yyyymm:   Optional[int] = None,
):
    """Monthly mood & productivity series."""
    conn = get_conn()
    conds, params = [], []
    if from_yyyymm:
        conds.append("yyyymm >= ?"); params.append(from_yyyymm)
    if to_yyyymm:
        conds.append("yyyymm <= ?"); params.append(to_yyyymm)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    rows = conn.execute(
        f"SELECT * FROM monthly_series {where} ORDER BY yyyymm ASC", params
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/skills")
def skills():
    """Skill radar values."""
    return _fetch_skills()


@app.get("/api/okrs")
def okrs(season: Optional[str] = None):
    """OKR board with key results."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM okrs" + (" WHERE season=?" if season else ""),
        ([season] if season else []),
    ).fetchall()
    result = []
    for r in rows:
        okr = dict(r)
        krs = conn.execute(
            "SELECT title, progress FROM key_results WHERE okr_id=? ORDER BY sort_order",
            (okr["id"],),
        ).fetchall()
        okr["key_results"] = [dict(k) for k in krs]
        result.append(okr)
    conn.close()
    return result


@app.get("/api/stats")
def stats():
    """Aggregate statistics."""
    return _get_summary_stats()


@app.get("/api/event-types")
def event_types():
    """All event type metadata."""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM event_types").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── AI endpoints ───────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    pass  # no body needed; all data comes from DB


class ExportRequest(BaseModel):
    public_only: bool = False


class ChatRequest(BaseModel):
    message: str


@app.post("/api/analyze")
def analyze():
    """
    Run the /analyze AI report.
    Requires ANTHROPIC_API_KEY env var.
    """
    _check_api_key()
    agent = get_agent()
    report = agent.chat("/analyze")
    return {"report": report}


@app.post("/api/export")
def export_events(req: ExportRequest):
    """
    Run /export — returns AI-polished event JSON for PDF rendering.
    Requires ANTHROPIC_API_KEY env var.
    """
    _check_api_key()
    agent = get_agent()
    cmd = "/export --public" if req.public_only else "/export"
    result = agent.chat(cmd)
    return {"output": result}


@app.post("/api/chat")
def chat(req: ChatRequest):
    """
    Free-form chat with the Livetime AI assistant.
    Supports slash commands (/timeline, /analyze, /export) and natural language.
    Requires ANTHROPIC_API_KEY env var.
    """
    _check_api_key()
    agent = get_agent()
    reply = agent.chat(req.message)
    return {"reply": reply}


def _check_api_key():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY not set — AI features unavailable",
        )


# ── entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = 8080
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        port = int(sys.argv[idx + 1])

    print(f"Livetime API running at http://127.0.0.1:{port}")
    print(f"Docs: http://127.0.0.1:{port}/docs")
    uvicorn.run("api_server:app", host="127.0.0.1", port=port, reload=True)
