"""
Livetime MCP Server
====================
Exposes the Livetime 時光機 timeline database to AI agents via the
Model Context Protocol (MCP).

Run:
    pip install fastmcp
    python mcp_server.py

Or via stdio (for Claude Desktop / MCP host):
    python mcp_server.py --stdio
"""
import json
import sqlite3
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP

DB_PATH = Path(__file__).parent / "livetime.db"

mcp = FastMCP(
    name="livetime",
    instructions=(
        "You are connected to the Livetime 時光機 personal timeline database. "
        "Use the available tools to query life events, mood series, OKRs, and skills. "
        "All text content is in Traditional Chinese."
    ),
)


# ── helpers ────────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


# ── tools ──────────────────────────────────────────────────────────────────

@mcp.tool()
def fetch_timeline_events(
    year: Optional[int] = None,
    category: Optional[str] = None,
    momentum: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """
    Retrieve timeline events with optional filters.

    Args:
        year:      Filter by year, e.g. 2025. Matches events whose date_sort
                   starts with that year (yyyymm ÷ 100 == year).
        category:  Filter by event type key: learn | work | intern | job | life
        momentum:  Filter by momentum key: up | calm | intense
        tag:       Filter by tag name (partial match, case-insensitive).
        limit:     Max number of events to return (default 50).
        offset:    Pagination offset (default 0).

    Returns a dict with:
        - events: list of event objects (with tags array attached)
        - total:  total count matching the filters (ignoring limit/offset)
    """
    conn = _conn()

    conditions: list[str] = []
    params: list = []

    if year is not None:
        conditions.append("e.date_sort / 100 = ?")
        params.append(year)
    if category is not None:
        conditions.append("e.type = ?")
        params.append(category)
    if momentum is not None:
        conditions.append("e.momentum = ?")
        params.append(momentum)
    if tag is not None:
        conditions.append(
            "e.id IN (SELECT et.event_id FROM event_tags et "
            "JOIN tags t ON t.id = et.tag_id WHERE t.name LIKE ?)"
        )
        params.append(f"%{tag}%")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    total = conn.execute(
        f"SELECT COUNT(*) FROM events e {where}", params
    ).fetchone()[0]

    rows = conn.execute(
        f"""SELECT e.id, e.title, e.date_label, e.date_sort,
                   e.year, e.month,
                   e.type, et_type.label AS type_label,
                   e.momentum, m.label AS momentum_label, m.color AS momentum_color,
                   e.description, e.has_media, e.link
            FROM events e
            LEFT JOIN event_types  et_type ON et_type.key = e.type
            LEFT JOIN momentum_types m      ON m.key = e.momentum
            {where}
            ORDER BY e.date_sort DESC
            LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()

    events = _rows_to_dicts(rows)

    # attach tags
    for ev in events:
        tag_rows = conn.execute(
            """SELECT t.name FROM tags t
               JOIN event_tags et ON et.tag_id = t.id
               WHERE et.event_id = ?""",
            (ev["id"],),
        ).fetchall()
        ev["tags"] = [r["name"] for r in tag_rows]
        ev["has_media"] = bool(ev["has_media"])

    conn.close()
    return {"events": events, "total": total}


@mcp.tool()
def get_event_detail(event_id: str) -> dict:
    """
    Retrieve full details for a single event by its ID (e.g. "e1").

    Returns the event object with tags, or raises an error if not found.
    """
    conn = _conn()
    row = conn.execute(
        """SELECT e.*, et_type.label AS type_label, et_type.icon AS type_icon,
                  m.label AS momentum_label, m.color AS momentum_color, m.icon AS momentum_icon
           FROM events e
           LEFT JOIN event_types   et_type ON et_type.key = e.type
           LEFT JOIN momentum_types m       ON m.key       = e.momentum
           WHERE e.id = ?""",
        (event_id,),
    ).fetchone()

    if row is None:
        raise ValueError(f"Event '{event_id}' not found.")

    ev = dict(row)
    tag_rows = conn.execute(
        "SELECT t.name FROM tags t JOIN event_tags et ON et.tag_id=t.id WHERE et.event_id=?",
        (event_id,),
    ).fetchall()
    ev["tags"] = [r["name"] for r in tag_rows]
    ev["has_media"] = bool(ev["has_media"])
    conn.close()
    return ev


@mcp.tool()
def fetch_mood_series(
    from_yyyymm: Optional[int] = None,
    to_yyyymm: Optional[int] = None,
) -> list[dict]:
    """
    Retrieve the monthly mood & productivity series.

    Args:
        from_yyyymm: Start month inclusive, e.g. 202301.
        to_yyyymm:   End month inclusive, e.g. 202612.

    Returns a list ordered by yyyymm ascending:
        [{ "month": "23/05", "yyyymm": 202305, "mood": 78, "prod": 42 }, ...]
    """
    conn = _conn()
    conditions = []
    params: list = []
    if from_yyyymm is not None:
        conditions.append("yyyymm >= ?")
        params.append(from_yyyymm)
    if to_yyyymm is not None:
        conditions.append("yyyymm <= ?")
        params.append(to_yyyymm)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM monthly_series {where} ORDER BY yyyymm ASC", params
    ).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


@mcp.tool()
def fetch_okrs(season: Optional[str] = None) -> list[dict]:
    """
    Retrieve OKRs with their key results.

    Args:
        season: Optional filter, e.g. "2026 上半年" or "長期".

    Returns a list of OKR objects, each with a `key_results` array.
    """
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM okrs" + (" WHERE season = ?" if season else ""),
        ([season] if season else []),
    ).fetchall()
    okrs = _rows_to_dicts(rows)
    for okr in okrs:
        kr_rows = conn.execute(
            "SELECT title, progress FROM key_results WHERE okr_id=? ORDER BY sort_order",
            (okr["id"],),
        ).fetchall()
        okr["key_results"] = _rows_to_dicts(kr_rows)
    conn.close()
    return okrs


@mcp.tool()
def fetch_skills() -> list[dict]:
    """
    Retrieve the skill radar data.

    Returns: [{ "name": "UI 設計", "value": 88 }, ...]
    """
    conn = _conn()
    rows = conn.execute("SELECT name, value FROM skills ORDER BY value DESC").fetchall()
    conn.close()
    return _rows_to_dicts(rows)


@mcp.tool()
def search_events(query: str, limit: int = 20) -> list[dict]:
    """
    Full-text search across event titles, descriptions, and tags.

    Args:
        query: Search keyword (searches title + description + tags).
        limit: Max results (default 20).

    Returns a list of matching event summaries.
    """
    conn = _conn()
    like = f"%{query}%"
    rows = conn.execute(
        """SELECT DISTINCT e.id, e.title, e.date_label, e.type, e.momentum, e.description
           FROM events e
           LEFT JOIN event_tags et ON et.event_id = e.id
           LEFT JOIN tags t        ON t.id = et.tag_id
           WHERE e.title LIKE ? OR e.description LIKE ? OR t.name LIKE ?
           ORDER BY e.date_sort DESC
           LIMIT ?""",
        (like, like, like, limit),
    ).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


@mcp.tool()
def get_summary_stats() -> dict:
    """
    Return aggregate statistics for the entire timeline.

    Includes: event count, category breakdown, momentum breakdown,
    date range, and all unique tags.
    """
    conn = _conn()

    total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    by_type = _rows_to_dicts(
        conn.execute(
            """SELECT e.type, et.label, COUNT(*) AS count
               FROM events e JOIN event_types et ON et.key = e.type
               GROUP BY e.type ORDER BY count DESC"""
        ).fetchall()
    )

    by_momentum = _rows_to_dicts(
        conn.execute(
            """SELECT e.momentum, m.label, COUNT(*) AS count
               FROM events e JOIN momentum_types m ON m.key = e.momentum
               GROUP BY e.momentum ORDER BY count DESC"""
        ).fetchall()
    )

    date_range = conn.execute(
        "SELECT MIN(date_sort) AS earliest, MAX(date_sort) AS latest FROM events"
    ).fetchone()

    all_tags = [
        r["name"]
        for r in conn.execute(
            "SELECT t.name, COUNT(et.event_id) AS n FROM tags t "
            "JOIN event_tags et ON et.tag_id=t.id GROUP BY t.id ORDER BY n DESC"
        ).fetchall()
    ]

    conn.close()
    return {
        "total_events": total,
        "by_category": by_type,
        "by_momentum": by_momentum,
        "date_range": {"earliest": date_range["earliest"], "latest": date_range["latest"]},
        "all_tags": all_tags,
    }


# ── entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if "--stdio" in sys.argv:
        mcp.run(transport="stdio")
    else:
        # default: SSE transport on localhost:8000
        mcp.run(transport="sse", host="127.0.0.1", port=8000)
