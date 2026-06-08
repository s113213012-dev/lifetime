#!/usr/bin/env python3
"""
Livetime 時光機 — 一鍵建檔腳本
================================
執行此腳本即可在本地自動建立完整的資料夾結構與所有專案檔案。

用法：
    python setup.py              # 建立在當前目錄的 ./livetime-project/
    python setup.py /my/path     # 建立在指定目錄

建立後的結構：
    livetime-project/
    ├── backend/
    │   ├── schema.sql
    │   ├── seed.py
    │   ├── api_server.py
    │   ├── mcp_server.py        (Phase 1，MCP 協議)
    │   ├── agent.py             (Phase 2，AI Agent)
    │   ├── agent_system_prompt.md
    │   └── requirements.txt
    └── frontend/
        └── index.html
"""
import subprocess
import sys
from pathlib import Path

# ── ANSI colors ────────────────────────────────────────────────────────────
G = "\033[92m"   # green
B = "\033[94m"   # blue
Y = "\033[93m"   # yellow
R = "\033[91m"   # red
BOLD = "\033[1m"
RST = "\033[0m"

def ok(msg):  print(f"  {G}✓{RST} {msg}")
def info(msg):print(f"  {B}→{RST} {msg}")
def warn(msg):print(f"  {Y}⚠{RST} {msg}")
def err(msg): print(f"  {R}✗{RST} {msg}")


# ══════════════════════════════════════════════════════════════════════════════
# FILE CONTENTS
# Each constant holds the exact file content as a raw string.
# ══════════════════════════════════════════════════════════════════════════════

# ── backend/schema.sql ────────────────────────────────────────────────────
SCHEMA_SQL = """\
-- Livetime 時光機 — SQLite Schema
-- Phase 1: core tables mirroring the frontend data model

-- ── Event types (learn / work / intern / job / life) ──────────────────────
CREATE TABLE IF NOT EXISTS event_types (
    key     TEXT PRIMARY KEY,
    label   TEXT NOT NULL,
    icon    TEXT NOT NULL,
    color   TEXT NOT NULL
);

-- ── Momentum / mood micro-badges ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS momentum_types (
    key     TEXT PRIMARY KEY,
    label   TEXT NOT NULL,
    icon    TEXT NOT NULL,
    color   TEXT NOT NULL,
    soft    TEXT NOT NULL    -- rgba string for background tint
);

-- ── Timeline events (main table) ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS events (
    id          TEXT    PRIMARY KEY,        -- e.g. "e1"
    title       TEXT    NOT NULL,
    date_label  TEXT    NOT NULL,           -- display string, e.g. "2026 · 3月"
    date_sort   INTEGER NOT NULL,           -- sortable yyyymm, e.g. 202603
    year        INTEGER GENERATED ALWAYS AS (date_sort / 100) VIRTUAL,
    month       INTEGER GENERATED ALWAYS AS (date_sort % 100) VIRTUAL,
    type        TEXT    NOT NULL REFERENCES event_types(key),
    momentum    TEXT    REFERENCES momentum_types(key),
    description TEXT,
    has_media   INTEGER NOT NULL DEFAULT 0, -- boolean 0/1
    link        TEXT,                       -- optional URL
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── Tags (many-to-many) ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tags (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT    NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS event_tags (
    event_id  TEXT    NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    tag_id    INTEGER NOT NULL REFERENCES tags(id)   ON DELETE CASCADE,
    PRIMARY KEY (event_id, tag_id)
);

-- ── Monthly mood / productivity series ───────────────────────────────────
CREATE TABLE IF NOT EXISTS monthly_series (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    month   TEXT    NOT NULL UNIQUE, -- "23/05" format for display
    yyyymm  INTEGER NOT NULL UNIQUE, -- 202305 for sorting
    mood    INTEGER NOT NULL CHECK(mood BETWEEN 0 AND 100),
    prod    INTEGER NOT NULL CHECK(prod BETWEEN 0 AND 100)
);

-- ── OKR board ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS okrs (
    id      TEXT    PRIMARY KEY,
    season  TEXT    NOT NULL,
    obj     TEXT    NOT NULL,   -- objective
    color   TEXT
);

CREATE TABLE IF NOT EXISTS key_results (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    okr_id    TEXT    NOT NULL REFERENCES okrs(id) ON DELETE CASCADE,
    title     TEXT    NOT NULL,
    progress  INTEGER NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
    sort_order INTEGER NOT NULL DEFAULT 0
);

-- ── Skill radar ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS skills (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT    NOT NULL UNIQUE,
    value INTEGER NOT NULL CHECK(value BETWEEN 0 AND 100)
);

-- ── Indexes ───────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_events_date_sort ON events(date_sort DESC);
CREATE INDEX IF NOT EXISTS idx_events_type      ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_momentum  ON events(momentum);
CREATE INDEX IF NOT EXISTS idx_event_tags_event ON event_tags(event_id);
CREATE INDEX IF NOT EXISTS idx_event_tags_tag   ON event_tags(tag_id);
"""


# ── backend/requirements.txt ──────────────────────────────────────────────
REQUIREMENTS_TXT = """\
fastmcp>=2.0.0
anthropic>=0.40.0
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
"""


# ── backend/seed.py ───────────────────────────────────────────────────────
SEED_PY = '''\
"""seed.py — populate the database with the sample data from the HTML prototype."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "livetime.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def seed():
    conn = get_conn()
    conn.executescript(SCHEMA_PATH.read_text())

    conn.executemany(
        "INSERT OR REPLACE INTO event_types(key, label, icon, color) VALUES(?,?,?,?)",
        [
            ("learn",  "學習", "learn",  "var(--t-learn)"),
            ("work",   "作品", "work",   "var(--t-work)"),
            ("intern", "實習", "intern", "var(--t-intern)"),
            ("job",    "工作", "job",    "var(--t-job)"),
            ("life",   "生活", "life",   "var(--t-life)"),
        ],
    )

    conn.executemany(
        "INSERT OR REPLACE INTO momentum_types(key, label, icon, color, soft) VALUES(?,?,?,?,?)",
        [
            ("up",      "成就感高", "arrowUp", "#34e3a8", "rgba(52,227,168,.16)"),
            ("calm",    "沉澱期",   "wave",    "#5ad1ff", "rgba(90,209,255,.16)"),
            ("intense", "高壓衝刺", "bolt",    "#ffc861", "rgba(255,200,97,.16)"),
        ],
    )

    events = [
        ("e1",  "Livetime 個人時光軸上線",      "2026 · 3月",        202603, "work",   "up",
         "把四年的學習、作品與生活收進一條互動時間軸，串接 AI 自動標籤與情緒分析。設計、前端到部署一手包辦。",
         1, "livetime.app"),
        ("e2",  "HackTime 黑客松 — 最佳設計獎", "2026 · 1月",        202601, "work",   "intense",
         "36 小時內帶領三人小組做出一款記帳語音助理，負責產品流程與全部視覺。第一次上台 Demo。",
         1, None),
        ("e3",  "星辰科技 — UI/UX 設計實習",    "2025 · 9月 – 12月", 202509, "intern", "intense",
         "在真實產品團隊裡畫了 20+ 份 Wireframe、整理一套設計系統元件庫。主管很願意帶人，但專案後期密集加班。",
         0, None),
        ("e4",  "完成 Google UX Design 認證",    "2025 · 6月",        202506, "learn",  "up",
         "七門課、一份完整作品集專案。最大的收穫是學會用使用者研究替設計決策說話。",
         0, "coursera.org"),
        ("e5",  "自學 Python 與資料視覺化",      "2025 · 3月",        202503, "learn",  "calm",
         "寒假慢慢啃 pandas 與 matplotlib，替系上活動做了一份報名數據儀表板。步調很慢但很踏實。",
         1, None),
        ("e6",  "校園導覽 App — 大三專題",       "2024 · 11月",       202411, "work",   "up",
         "帶四人團隊從訪談、原型到使用者測試，做出一款新生校園導覽 App，期末拿到全班最高分。",
         1, None),
        ("e7",  "暑期打工 + 一個人的東部旅行",   "2024 · 7月",        202407, "life",   "calm",
         "在咖啡廳打工兩個月，存下旅費，獨自搭火車環島東半部。把生活按下慢速鍵，反而想清楚想做的方向。",
         1, None),
        ("e8",  "設計社 — 接任視覺組長",         "2024 · 2月",        202402, "job",    "up",
         "統籌社團一整年的視覺識別與活動主視覺，第一次管理一個六人的設計小組。學會把品味變成可溝通的規則。",
         0, None),
        ("e9",  "升大三 · 主修使用者經驗",       "2023 · 9月",        202309, "learn",  "calm",
         "正式選定 HCI 與互動設計方向，開始大量閱讀設計理論，也常常懷疑自己到底適不適合。",
         0, None),
        ("e10", "第一個 Figma 作品",             "2023 · 5月",        202305, "learn",  "up",
         "照著 YouTube 教學重做了一遍音樂 App 介面，第一次感受到把腦中畫面變成像素的快樂。一切的起點。",
         1, None),
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO events"
        "(id, title, date_label, date_sort, type, momentum, description, has_media, link)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        events,
    )

    raw_tags = {
        "e1":  ["UI/UX", "React", "資料視覺化", "Side Project"],
        "e2":  ["Product Design", "Figma", "Pitch"],
        "e3":  ["Figma", "Wireframing", "Design System", "協作"],
        "e4":  ["UX Research", "Prototyping", "可用性測試"],
        "e5":  ["Python", "資料分析", "Matplotlib"],
        "e6":  ["專案管理", "UI", "使用者研究"],
        "e7":  ["充電", "攝影", "生活"],
        "e8":  ["Leadership", "品牌設計", "Branding"],
        "e9":  ["HCI", "互動設計"],
        "e10": ["Figma", "UI"],
    }
    for event_id, tag_names in raw_tags.items():
        for name in tag_names:
            conn.execute("INSERT OR IGNORE INTO tags(name) VALUES(?)", (name,))
            row = conn.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()
            conn.execute(
                "INSERT OR IGNORE INTO event_tags(event_id, tag_id) VALUES(?,?)",
                (event_id, row["id"]),
            )

    series = [
        ("23/05", 202305, 78, 42), ("23/09", 202309, 54, 50),
        ("24/02", 202402, 80, 68), ("24/07", 202407, 62, 30),
        ("24/11", 202411, 88, 82), ("25/03", 202503, 58, 55),
        ("25/06", 202506, 84, 74), ("25/09", 202509, 60, 92),
        ("25/12", 202512, 48, 88), ("26/01", 202601, 72, 95),
        ("26/03", 202603, 90, 80),
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO monthly_series(month, yyyymm, mood, prod) VALUES(?,?,?,?)",
        series,
    )

    okrs = [
        ("o1", "2026 上半年", "成為能獨當一面的產品設計師", "var(--t-work)"),
        ("o2", "2026 上半年", "補強工程與資料能力",         "var(--t-learn)"),
        ("o3", "長期",        "維持身心的續航力",           "var(--t-life)"),
    ]
    conn.executemany("INSERT OR REPLACE INTO okrs(id, season, obj, color) VALUES(?,?,?,?)", okrs)

    krs = [
        ("o1", "產出一份完整的個人作品集網站", 100, 0),
        ("o1", "主導一個 0→1 的產品專案",      65,  1),
        ("o1", "累積 3 場公開設計分享",         33,  2),
        ("o2", "用 React 獨立完成 2 個專案",    80,  0),
        ("o2", "學會用資料佐證設計決策",         50,  1),
        ("o2", "讀完《Design for Real Life》",  20,  2),
        ("o3", "每週運動 3 次",                 45,  0),
        ("o3", "每季安排一次完整休假",           75,  1),
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO key_results(okr_id, title, progress, sort_order) VALUES(?,?,?,?)",
        krs,
    )

    skills = [
        ("UI 設計",   88), ("使用者研究", 72), ("前端開發",   64),
        ("專案管理",   70), ("資料分析",   48), ("品牌視覺",   78),
    ]
    conn.executemany("INSERT OR REPLACE INTO skills(name, value) VALUES(?,?)", skills)

    conn.commit()
    conn.close()
    print(f"✓ Database seeded at {DB_PATH}")


if __name__ == "__main__":
    seed()
'''


# ── backend/api_server.py ─────────────────────────────────────────────────
API_SERVER_PY = '''\
"""
api_server.py — Livetime REST API
===================================
Thin HTTP wrapper around the SQLite helpers.

    python api_server.py            # default :8080
    python api_server.py --port 3001

CORS is open so GitHub Pages (or any origin) can reach a local/ngrok server.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent))
from agent import (
    _fetch_events, _fetch_mood_series, _fetch_skills,
    _get_summary_stats, LivetimeAgent,
)
from seed import get_conn

app = FastAPI(title="Livetime API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_agent: LivetimeAgent | None = None

def get_agent() -> LivetimeAgent:
    global _agent
    if _agent is None:
        _agent = LivetimeAgent()
    return _agent


@app.get("/api/events")
def list_events(
    year: Optional[int] = None, category: Optional[str] = None,
    momentum: Optional[str] = None, tag: Optional[str] = None,
    limit: int = 50, offset: int = 0,
):
    return _fetch_events(
        year=year, category=category, momentum=momentum,
        tag=tag, limit=min(int(limit), 200), offset=int(offset),
    )


@app.get("/api/events/{event_id}")
def get_event(event_id: str):
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
        raise HTTPException(status_code=404, detail=f"Event \'{event_id}\' not found")
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


@app.get("/api/mood-series")
def mood_series(from_yyyymm: Optional[int] = None, to_yyyymm: Optional[int] = None):
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
    return _fetch_skills()


@app.get("/api/okrs")
def okrs(season: Optional[str] = None):
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
    return _get_summary_stats()


@app.get("/api/event-types")
def event_types():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM event_types").fetchall()
    conn.close()
    return [dict(r) for r in rows]


class ExportRequest(BaseModel):
    public_only: bool = False

class ChatRequest(BaseModel):
    message: str


def _check_api_key():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY not set — AI features unavailable",
        )


@app.post("/api/analyze")
def analyze():
    _check_api_key()
    return {"report": get_agent().chat("/analyze")}


@app.post("/api/export")
def export_events(req: ExportRequest):
    _check_api_key()
    cmd = "/export --public" if req.public_only else "/export"
    return {"output": get_agent().chat(cmd)}


@app.post("/api/chat")
def chat(req: ChatRequest):
    _check_api_key()
    return {"reply": get_agent().chat(req.message)}


if __name__ == "__main__":
    port = 8080
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    print(f"Livetime API → http://127.0.0.1:{port}")
    print(f"Docs          → http://127.0.0.1:{port}/docs")
    uvicorn.run("api_server:app", host="127.0.0.1", port=port, reload=True)
'''


# ── backend/agent.py ──────────────────────────────────────────────────────
AGENT_PY = '''\
"""
agent.py — Livetime AI Agent
Slash-command parser + Anthropic API integration.

    python agent.py                        # interactive REPL
    python agent.py "/timeline 2025 work"  # single command
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import anthropic
from anthropic import Anthropic

from seed import get_conn

SYSTEM_PROMPT = (Path(__file__).parent / "agent_system_prompt.md").read_text(
    encoding="utf-8"
)

CATEGORY_ALIASES: dict[str, str] = {
    "學習": "learn", "learn": "learn",
    "作品": "work",  "work":  "work",
    "實習": "intern","intern":"intern",
    "工作": "job",   "job":   "job",
    "生活": "life",  "life":  "life",
}

MOMENTUM_EMOJI = {"up": "⬆️", "calm": "🌊", "intense": "⚡"}


def _fetch_events(
    year=None, category=None, momentum=None, tag=None, limit=100, offset=0,
) -> dict[str, Any]:
    conn = get_conn()
    conds, params = [], []
    if year:
        conds.append("e.date_sort / 100 = ?"); params.append(year)
    if category:
        conds.append("e.type = ?"); params.append(category)
    if momentum:
        conds.append("e.momentum = ?"); params.append(momentum)
    if tag:
        conds.append(
            "e.id IN (SELECT et.event_id FROM event_tags et "
            "JOIN tags t ON t.id=et.tag_id WHERE t.name LIKE ?)"
        )
        params.append(f"%{tag}%")
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    total = conn.execute(f"SELECT COUNT(*) FROM events e {where}", params).fetchone()[0]
    rows = conn.execute(
        f"""SELECT e.id, e.title, e.date_label, e.date_sort, e.year, e.month,
                   e.type, et.label AS type_label,
                   e.momentum, m.label AS momentum_label, m.color AS momentum_color,
                   e.description, e.has_media, e.link
            FROM events e
            LEFT JOIN event_types    et ON et.key=e.type
            LEFT JOIN momentum_types m  ON m.key=e.momentum
            {where} ORDER BY e.date_sort DESC LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()
    events = [dict(r) for r in rows]
    for ev in events:
        tag_rows = conn.execute(
            "SELECT t.name FROM tags t JOIN event_tags et ON et.tag_id=t.id WHERE et.event_id=?",
            (ev["id"],),
        ).fetchall()
        ev["tags"] = [r["name"] for r in tag_rows]
        ev["has_media"] = bool(ev["has_media"])
    conn.close()
    return {"events": events, "total": total}


def _fetch_mood_series():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM monthly_series ORDER BY yyyymm ASC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _fetch_skills():
    conn = get_conn()
    rows = conn.execute("SELECT name, value FROM skills ORDER BY value DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_summary_stats():
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    by_type = [dict(r) for r in conn.execute(
        "SELECT e.type, et.label, COUNT(*) AS count FROM events e "
        "JOIN event_types et ON et.key=e.type GROUP BY e.type ORDER BY count DESC"
    ).fetchall()]
    date_range = dict(conn.execute(
        "SELECT MIN(date_sort) AS earliest, MAX(date_sort) AS latest FROM events"
    ).fetchone())
    all_tags = [r["name"] for r in conn.execute(
        "SELECT t.name, COUNT(et.event_id) n FROM tags t "
        "JOIN event_tags et ON et.tag_id=t.id GROUP BY t.id ORDER BY n DESC"
    ).fetchall()]
    conn.close()
    return {"total_events": total, "by_category": by_type,
            "date_range": date_range, "all_tags": all_tags}


def render_timeline(year, category):
    result = _fetch_events(year=year, category=category)
    events = result["events"]
    total = result["total"]

    if not events:
        parts = []
        if year:     parts.append(f"{year} 年")
        if category: parts.append(f"分類：{category}")
        desc = f"（{\'·\'.join(parts)}）" if parts else ""
        return f"> 找不到符合條件的事件{desc}。"

    lines: list[str] = []
    for ev in events:
        emoji = MOMENTUM_EMOJI.get(ev.get("momentum", ""), "")
        tags_str = " ".join(f"`{t}`" for t in ev.get("tags", []))
        link_line = f"🔗 [{ev[\'link\']}]({ev[\'link\']})" if ev.get("link") else ""
        block = [
            "---",
            f"### {ev[\'date_label\']} · {ev.get(\'type_label\', ev[\'type\'])}",
            "",
            f"**{ev[\'title\']}**",
            "",
            ev.get("description") or "",
            "",
            f"**情緒狀態**：{emoji} {ev.get(\'momentum_label\', \'\')}",
            f"**技能標籤**：{tags_str}",
        ]
        if link_line:
            block.append(link_line)
        lines.extend(block)
        lines.append("")

    parts = []
    if year:     parts.append(f"{year} 年")
    if category: parts.append(f"分類：{category}")
    desc = f"（{\'·\'.join(parts)}）" if parts else ""
    lines.append(f"> 共 {total} 筆事件{desc}")
    return "\\n".join(lines)


def build_analyze_context():
    ctx = {
        "summary_stats": _get_summary_stats(),
        "events": [
            {k: v for k, v in e.items()
             if k in ("id","title","date_label","date_sort","type","type_label",
                      "momentum","momentum_label","description","tags")}
            for e in _fetch_events(limit=100)["events"]
        ],
        "mood_series": _fetch_mood_series(),
        "skills": _fetch_skills(),
    }
    return json.dumps(ctx, ensure_ascii=False, indent=2)


def build_export_context(public_only):
    events = _fetch_events(limit=100)["events"]
    if public_only:
        events = [e for e in events if e["type"] != "life"]
    counts: dict[str, int] = {}
    for e in events:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    return events, {"total": len(events), "categories": counts}


def parse_slash(text):
    text = text.strip()
    if not text.startswith("/"):
        return "chat", {"text": text}
    parts = text.split()
    cmd = parts[0].lstrip("/").lower()
    if cmd == "timeline":
        year, category = None, None
        for token in parts[1:]:
            if re.fullmatch(r"\\d{4}", token):
                year = int(token)
            elif token.lower() in CATEGORY_ALIASES:
                category = CATEGORY_ALIASES[token.lower()]
        return "timeline", {"year": year, "category": category}
    if cmd == "analyze":
        return "analyze", {}
    if cmd == "export":
        return "export", {"public_only": "--public" in parts}
    return "unknown", {"original": text}


UNKNOWN_HELP = """目前支援的指令：
• `/timeline [年份] [分類]` — 瀏覽時間軸
• `/analyze` — 深度洞察報告
• `/export [--public]` — 匯出作品集 JSON

輸入指令或直接用自然語言問我！"""


class LivetimeAgent:
    def __init__(self, model: str = "claude-opus-4-8"):
        self.client = Anthropic()
        self.model = model
        self.history: list[dict] = []

    def chat(self, user_input: str) -> str:
        cmd, kwargs = parse_slash(user_input)
        if cmd == "timeline":
            return render_timeline(kwargs["year"], kwargs["category"])
        if cmd == "unknown":
            return UNKNOWN_HELP
        if cmd == "analyze":
            context = build_analyze_context()
            injected = (
                "使用者輸入了 `/analyze`。\\n\\n"
                f"資料庫資料（JSON）：\\n\\n```json\\n{context}\\n```\\n\\n"
                "請依照 System Prompt 的 `/analyze` 格式生成完整洞察報告。"
            )
            return self._ask_claude(injected, stateful=False)
        if cmd == "export":
            events, meta = build_export_context(kwargs["public_only"])
            events_json = json.dumps(events, ensure_ascii=False, indent=2)
            flag = " --public" if kwargs["public_only"] else ""
            injected = (
                f"使用者輸入了 `/export{flag}`。\\n\\n"
                f"事件資料：\\n\\n```json\\n{events_json}\\n```\\n\\n"
                f"meta：{json.dumps(meta, ensure_ascii=False)}\\n"
                f"exported_at: {date.today().isoformat()}\\n\\n"
                "請依照 System Prompt 的 `/export` 格式潤飾並輸出 JSON。"
            )
            return self._ask_claude(injected, stateful=False)
        if cmd == "chat":
            text = kwargs["text"]
            data_kw = re.compile(
                r"事件|技能|心情|情緒|幾筆|做了什麼|分析|OKR|作品|實習|學習|工作|生活|Figma|Python|React",
                re.IGNORECASE,
            )
            if data_kw.search(text):
                stats = _get_summary_stats()
                text += f"\\n\\n[工具上下文] 統計摘要：{json.dumps(stats, ensure_ascii=False)}"
            return self._ask_claude(text, stateful=True)
        return UNKNOWN_HELP

    def _ask_claude(self, user_content: str, stateful: bool) -> str:
        messages = self.history + [{"role": "user", "content": user_content}]
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        reply = response.content[0].text
        if stateful:
            self.history.append({"role": "user", "content": user_content})
            self.history.append({"role": "assistant", "content": reply})
            self.history = self.history[-40:]
        return reply


def main():
    agent = LivetimeAgent()
    if len(sys.argv) > 1:
        print(agent.chat(" ".join(sys.argv[1:])))
        return
    print("時光機 AI 助理已啟動。輸入 /help 查看指令，Ctrl+C 離開。\\n")
    while True:
        try:
            user_input = input("你：").strip()
            if not user_input:
                continue
            print(f"\\n助理：\\n{agent.chat(user_input)}\\n")
        except KeyboardInterrupt:
            print("\\n掰掰！"); break


if __name__ == "__main__":
    main()
'''


# ── backend/agent_system_prompt.md ────────────────────────────────────────
AGENT_SYSTEM_PROMPT_MD = """\
# Livetime AI 助理 — System Prompt

你是「時光機 AI」，一個專為 **Livetime 個人時光軸** 設計的智慧助理。

## 身份定位
- 語氣：真誠、有溫度、具洞察力
- 語言：預設繁體中文
- 硬規則：不編造資料庫中不存在的事件；所有資料必須來自工具查詢

## 可用的 MCP 工具
| 工具 | 用途 |
|------|------|
| fetch_timeline_events | 以年份、分類、情緒狀態、標籤篩選事件 |
| get_event_detail | 取得單一事件完整資訊 |
| fetch_mood_series | 月度情緒與動能數列 |
| fetch_okrs | OKR 目標看板 |
| fetch_skills | 技能雷達數值 |
| search_events | 關鍵字全文搜尋 |
| get_summary_stats | 全局統計摘要 |

## /timeline [篩選條件]
- 呼叫 fetch_timeline_events，依下列格式輸出每張卡片：

```
---
### {date_label} · {type_label}
**{title}**
{description}
**情緒狀態**：{emoji} {momentum_label}
**技能標籤**：`tag1` `tag2`
```
momentum emoji：up=⬆️  calm=🌊  intense=⚡

## /analyze
依序呼叫全部工具，輸出含以下區塊的洞察報告：
📊 總覽 / 😌 情緒波動 / 🌱 技能成長 / 🗂 分類深潛 / 🚀 建議（3 項）
每條建議必須引用具體資料。

## /export [--public]
- --public：排除 type=life 的事件
- 對每筆 description 進行正式化潤飾（60-100 字）
- 輸出含 description_polished / description_original 的 JSON 程式碼區塊

## 未識別指令
回傳支援指令列表。
"""


# ── backend/mcp_server.py ─────────────────────────────────────────────────
MCP_SERVER_PY = '''\
"""
mcp_server.py — Livetime MCP Server
Exposes the timeline database to AI agents via the Model Context Protocol.

    python mcp_server.py           # SSE on http://127.0.0.1:8000/sse
    python mcp_server.py --stdio   # stdio (for Claude Desktop)
"""
import sqlite3
import sys
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP

DB_PATH = Path(__file__).parent / "livetime.db"

mcp = FastMCP(
    name="livetime",
    instructions=(
        "You are connected to the Livetime 時光機 personal timeline database. "
        "Use the tools to query life events, mood series, OKRs, and skills. "
        "All content is in Traditional Chinese."
    ),
)


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def _rows(rows): return [dict(r) for r in rows]


@mcp.tool()
def fetch_timeline_events(
    year: Optional[int] = None, category: Optional[str] = None,
    momentum: Optional[str] = None, tag: Optional[str] = None,
    limit: int = 50, offset: int = 0,
) -> dict:
    """Retrieve timeline events. Supports year, category, momentum, tag filters."""
    conn = _conn()
    conds, params = [], []
    if year:     conds.append("e.date_sort/100=?"); params.append(year)
    if category: conds.append("e.type=?");          params.append(category)
    if momentum: conds.append("e.momentum=?");      params.append(momentum)
    if tag:
        conds.append("e.id IN (SELECT et.event_id FROM event_tags et "
                     "JOIN tags t ON t.id=et.tag_id WHERE t.name LIKE ?)")
        params.append(f"%{tag}%")
    where = ("WHERE "+" AND ".join(conds)) if conds else ""
    total = conn.execute(f"SELECT COUNT(*) FROM events e {where}", params).fetchone()[0]
    rows = conn.execute(
        f"""SELECT e.id,e.title,e.date_label,e.date_sort,e.year,e.month,
                   e.type,et.label AS type_label,
                   e.momentum,m.label AS momentum_label,
                   e.description,e.has_media,e.link
            FROM events e
            LEFT JOIN event_types et ON et.key=e.type
            LEFT JOIN momentum_types m ON m.key=e.momentum
            {where} ORDER BY e.date_sort DESC LIMIT ? OFFSET ?""",
        params+[limit, offset],
    ).fetchall()
    events = _rows(rows)
    for ev in events:
        tr = conn.execute(
            "SELECT t.name FROM tags t JOIN event_tags et ON et.tag_id=t.id WHERE et.event_id=?",
            (ev["id"],),
        ).fetchall()
        ev["tags"] = [r["name"] for r in tr]
        ev["has_media"] = bool(ev["has_media"])
    conn.close()
    return {"events": events, "total": total}


@mcp.tool()
def get_event_detail(event_id: str) -> dict:
    """Get full details for a single event by ID."""
    conn = _conn()
    row = conn.execute(
        "SELECT e.*,et.label AS type_label,m.label AS momentum_label "
        "FROM events e LEFT JOIN event_types et ON et.key=e.type "
        "LEFT JOIN momentum_types m ON m.key=e.momentum WHERE e.id=?",
        (event_id,),
    ).fetchone()
    if row is None: raise ValueError(f"Event \'{event_id}\' not found")
    ev = dict(row)
    ev["tags"] = [r["name"] for r in conn.execute(
        "SELECT t.name FROM tags t JOIN event_tags et ON et.tag_id=t.id WHERE et.event_id=?",
        (event_id,),
    ).fetchall()]
    conn.close()
    return ev


@mcp.tool()
def fetch_mood_series(from_yyyymm: Optional[int]=None, to_yyyymm: Optional[int]=None) -> list:
    """Monthly mood & productivity series."""
    conn = _conn()
    conds, params = [], []
    if from_yyyymm: conds.append("yyyymm>=?"); params.append(from_yyyymm)
    if to_yyyymm:   conds.append("yyyymm<=?"); params.append(to_yyyymm)
    where = ("WHERE "+" AND ".join(conds)) if conds else ""
    rows = conn.execute(f"SELECT * FROM monthly_series {where} ORDER BY yyyymm", params).fetchall()
    conn.close()
    return _rows(rows)


@mcp.tool()
def fetch_skills() -> list:
    """Skill radar values (0-100)."""
    conn = _conn()
    rows = conn.execute("SELECT name,value FROM skills ORDER BY value DESC").fetchall()
    conn.close()
    return _rows(rows)


@mcp.tool()
def fetch_okrs(season: Optional[str]=None) -> list:
    """OKR board with key results."""
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM okrs"+(" WHERE season=?" if season else ""),
        ([season] if season else []),
    ).fetchall()
    result = []
    for r in rows:
        okr = dict(r)
        okr["key_results"] = _rows(conn.execute(
            "SELECT title,progress FROM key_results WHERE okr_id=? ORDER BY sort_order",
            (okr["id"],),
        ).fetchall())
        result.append(okr)
    conn.close()
    return result


@mcp.tool()
def search_events(query: str, limit: int=20) -> list:
    """Full-text search across titles, descriptions, and tags."""
    conn = _conn()
    like = f"%{query}%"
    rows = conn.execute(
        "SELECT DISTINCT e.id,e.title,e.date_label,e.type,e.momentum,e.description "
        "FROM events e LEFT JOIN event_tags et ON et.event_id=e.id "
        "LEFT JOIN tags t ON t.id=et.tag_id "
        "WHERE e.title LIKE ? OR e.description LIKE ? OR t.name LIKE ? "
        "ORDER BY e.date_sort DESC LIMIT ?",
        (like, like, like, limit),
    ).fetchall()
    conn.close()
    return _rows(rows)


@mcp.tool()
def get_summary_stats() -> dict:
    """Aggregate statistics: counts, category breakdown, date range, all tags."""
    conn = _conn()
    total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    by_type = _rows(conn.execute(
        "SELECT e.type,et.label,COUNT(*) AS count FROM events e "
        "JOIN event_types et ON et.key=e.type GROUP BY e.type ORDER BY count DESC"
    ).fetchall())
    dr = dict(conn.execute(
        "SELECT MIN(date_sort) AS earliest,MAX(date_sort) AS latest FROM events"
    ).fetchone())
    tags = [r["name"] for r in conn.execute(
        "SELECT t.name,COUNT(et.event_id) n FROM tags t "
        "JOIN event_tags et ON et.tag_id=t.id GROUP BY t.id ORDER BY n DESC"
    ).fetchall()]
    conn.close()
    return {"total_events": total, "by_category": by_type, "date_range": dr, "all_tags": tags}


if __name__ == "__main__":
    if "--stdio" in sys.argv:
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="sse", host="127.0.0.1", port=8000)
'''


# ── frontend/index.html ───────────────────────────────────────────────────
# Read from a separate constant to keep it clean
INDEX_HTML = """\
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Livetime · 時光機</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#070b15;--bg-2:#0d1425;--bg-3:#131d30;--bg-card:rgba(13,20,37,.85);
  --a1:#34e3a8;--a2:#3da7fc;--a1-soft:rgba(52,227,168,.13);--a2-soft:rgba(61,167,252,.13);
  --glow:rgba(52,227,168,.45);--txt:#e8f0fe;--txt-2:#94a3c0;--txt-3:#556078;
  --border:rgba(255,255,255,.07);--radius:14px;
  --t-learn:#3da7fc;--t-work:#34e3a8;--t-intern:#c084fc;--t-job:#fbbf24;--t-life:#f472b6;
}
body{background:var(--bg);color:var(--txt);font-family:-apple-system,BlinkMacSystemFont,'Noto Sans TC',sans-serif;min-height:100vh;display:flex;flex-direction:column}
a{color:var(--a1);text-decoration:none}
button{cursor:pointer;border:none;background:none;color:inherit;font:inherit}
input,select,textarea{font:inherit;color:inherit;background:var(--bg-3);border:1px solid var(--border);border-radius:8px;outline:none}
input:focus,select:focus,textarea:focus{border-color:var(--a1);box-shadow:0 0 0 2px var(--a1-soft)}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--bg-3);border-radius:4px}
.shell{display:flex;height:100vh;overflow:hidden}
.sidebar{width:220px;flex-shrink:0;background:var(--bg-2);border-right:1px solid var(--border);display:flex;flex-direction:column;padding:20px 0}
.main{flex:1;overflow-y:auto;padding:28px 36px}
.logo{display:flex;align-items:center;gap:10px;padding:0 20px 24px;border-bottom:1px solid var(--border);margin-bottom:16px}
.logo-icon{width:32px;height:32px;background:linear-gradient(135deg,var(--a1),var(--a2));border-radius:8px;display:grid;place-items:center;font-size:16px}
.logo-text{font-weight:800;font-size:15px;letter-spacing:.3px}
.logo-sub{font-size:11px;color:var(--txt-3);margin-top:1px}
.nav-item{display:flex;align-items:center;gap:10px;padding:9px 20px;font-size:13.5px;color:var(--txt-2);transition:all .15s;border-left:2px solid transparent}
.nav-item:hover{color:var(--txt);background:var(--a1-soft)}
.nav-item.active{color:var(--a1);background:var(--a1-soft);border-left-color:var(--a1);font-weight:600}
.nav-icon{font-size:15px;width:18px;text-align:center}
.sidebar-footer{margin-top:auto;padding:16px 20px;border-top:1px solid var(--border);font-size:12px;color:var(--txt-3)}
.status-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--a1);margin-right:6px;box-shadow:0 0 6px var(--a1)}
.card{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);padding:20px;backdrop-filter:blur(8px)}
.page-title{font-size:22px;font-weight:800;margin-bottom:4px}
.page-sub{font-size:13px;color:var(--txt-3);margin-bottom:24px}
.filter-bar{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:24px;align-items:center}
.filter-bar select,.filter-bar input[type=text]{padding:7px 12px;font-size:13px;border-radius:8px;height:36px}
.filter-bar select{min-width:120px}
.filter-bar input[type=text]{flex:1;min-width:160px;max-width:260px}
.btn{display:inline-flex;align-items:center;gap:6px;padding:7px 16px;border-radius:8px;font-size:13px;font-weight:600;transition:all .15s;height:36px}
.btn-primary{background:linear-gradient(135deg,var(--a1),var(--a2));color:#070b15}
.btn-primary:hover{filter:brightness(1.1);box-shadow:0 0 16px var(--glow)}
.btn-ghost{border:1px solid var(--border);color:var(--txt-2)}
.btn-ghost:hover{border-color:var(--a1);color:var(--a1)}
.timeline-wrap{position:relative;padding-left:40px}
.timeline-axis{position:absolute;left:14px;top:0;bottom:0;width:2px;background:linear-gradient(to bottom,var(--a1),var(--a2));border-radius:2px}
.event-card{position:relative;margin-bottom:20px}
.event-dot{position:absolute;left:-33px;top:18px;width:14px;height:14px;border-radius:50%;border:2.5px solid var(--a1);background:var(--bg);box-shadow:0 0 10px var(--glow);transition:transform .15s}
.event-card:hover .event-dot{transform:scale(1.3)}
.event-inner{background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);padding:18px 20px;transition:border-color .15s}
.event-card:hover .event-inner{border-color:rgba(52,227,168,.35)}
.event-meta{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px}
.event-date{font-size:12px;color:var(--txt-3);font-weight:600;letter-spacing:.3px}
.type-badge{font-size:11px;font-weight:700;padding:2px 8px;border-radius:20px}
.momentum-badge{font-size:11px;font-weight:600;padding:2px 8px;border-radius:20px;display:flex;align-items:center;gap:4px}
.event-title{font-size:15.5px;font-weight:700;line-height:1.4;margin-bottom:6px}
.event-desc{font-size:13px;color:var(--txt-2);line-height:1.65}
.tag-row{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.tag{font-size:11.5px;padding:3px 9px;border-radius:6px;background:rgba(61,167,252,.12);color:var(--a2);border:1px solid rgba(61,167,252,.2);font-family:ui-monospace,monospace}
.event-link{margin-top:8px;font-size:12px;color:var(--a1)}
.event-link::before{content:"🔗 "}
.console-wrap{display:flex;flex-direction:column;height:calc(100vh - 56px - 80px);min-height:400px}
.console-log{flex:1;overflow-y:auto;padding:16px;background:var(--bg-2);border:1px solid var(--border);border-radius:var(--radius);font-size:13.5px;line-height:1.7;margin-bottom:14px}
.msg{margin-bottom:16px}
.msg-user .bubble{background:var(--a1-soft);border:1px solid rgba(52,227,168,.2);border-radius:12px 12px 4px 12px;padding:10px 14px;display:inline-block;max-width:80%;color:var(--txt)}
.msg-ai .bubble{background:var(--bg-3);border:1px solid var(--border);border-radius:4px 12px 12px 12px;padding:10px 14px;max-width:90%;white-space:pre-wrap}
.msg-label{font-size:11px;color:var(--txt-3);margin-bottom:4px;font-weight:600}
.msg-ai .msg-label{color:var(--a1)}
.console-input-row{display:flex;gap:10px}
.console-input{flex:1;padding:10px 14px;border-radius:10px;font-size:13.5px;resize:none;height:44px}
.loading-dots::after{content:"";animation:dots 1.2s infinite}
@keyframes dots{0%{content:""}33%{content:"."}66%{content:".."}100%{content:"..."}}
.stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:22px}
.stat-card{text-align:center;padding:18px 12px}
.stat-val{font-size:32px;font-weight:800;background:linear-gradient(135deg,var(--a1),var(--a2));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.stat-label{font-size:11.5px;color:var(--txt-3);font-weight:700;margin-top:4px}
.bar-chart{margin-top:14px}
.bar-row{display:flex;align-items:center;gap:10px;margin-bottom:8px;font-size:12.5px}
.bar-label{width:72px;color:var(--txt-2);font-weight:600;text-align:right}
.bar-track{flex:1;height:8px;border-radius:4px;background:var(--bg-3);overflow:hidden}
.bar-fill{height:100%;border-radius:4px;background:linear-gradient(90deg,var(--a2),var(--a1));transition:width .6s cubic-bezier(.22,1,.36,1)}
.bar-val{width:32px;color:var(--txt-3);font-size:11.5px;font-family:ui-monospace,monospace}
.sparkline-wrap{overflow-x:auto;padding-bottom:4px}
.skeleton{background:linear-gradient(90deg,var(--bg-3) 25%,var(--bg-2) 50%,var(--bg-3) 75%);background-size:200% 100%;animation:shimmer 1.4s infinite;border-radius:8px}
@keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}
.sk-card{height:120px;margin-bottom:20px;border-radius:var(--radius)}
#toast-root{position:fixed;bottom:24px;right:24px;display:flex;flex-direction:column;gap:8px;z-index:999}
.toast{padding:10px 16px;border-radius:10px;font-size:13px;font-weight:600;animation:slide-in .2s ease;border:1px solid var(--border)}
.toast-ok{background:var(--a1-soft);border-color:rgba(52,227,168,.3);color:var(--a1)}
.toast-err{background:rgba(248,113,113,.12);border-color:rgba(248,113,113,.3);color:#f87171}
@keyframes slide-in{from{transform:translateX(40px);opacity:0}to{transform:none;opacity:1}}
.section-title{font-size:14px;font-weight:800;color:var(--txt-2);text-transform:uppercase;letter-spacing:.6px;margin-bottom:14px}
.empty{text-align:center;padding:60px 0;color:var(--txt-3);font-size:14px}
.count-badge{font-size:12px;color:var(--txt-3);margin-left:auto}
.view{display:none}
.view.active{display:block}
</style>
</head>
<body>
<div id="toast-root"></div>
<div class="shell">
  <aside class="sidebar">
    <div class="logo">
      <div class="logo-icon">⏳</div>
      <div><div class="logo-text">Livetime</div><div class="logo-sub">時光機</div></div>
    </div>
    <button class="nav-item active" onclick="showView('timeline',this)"><span class="nav-icon">📅</span>時間軸</button>
    <button class="nav-item" onclick="showView('dashboard',this)"><span class="nav-icon">📊</span>總覽儀表板</button>
    <button class="nav-item" onclick="showView('console',this)"><span class="nav-icon">🤖</span>AI 助理</button>
    <div class="sidebar-footer"><span class="status-dot"></span><span id="api-status">連接中…</span></div>
  </aside>
  <main class="main">
    <div id="view-timeline" class="view active">
      <div class="page-title">時間軸</div>
      <div class="page-sub">我的學習、作品與人生記錄</div>
      <div class="filter-bar">
        <select id="filter-year" onchange="applyFilters()">
          <option value="">全部年份</option>
          <option value="2026">2026</option><option value="2025">2025</option>
          <option value="2024">2024</option><option value="2023">2023</option>
        </select>
        <select id="filter-cat" onchange="applyFilters()">
          <option value="">全部分類</option>
          <option value="learn">🎓 學習</option><option value="work">💼 作品</option>
          <option value="intern">🏢 實習</option><option value="job">👑 工作</option>
          <option value="life">🌿 生活</option>
        </select>
        <input type="text" id="filter-search" placeholder="搜尋關鍵字…" oninput="debounceSearch()">
        <button class="btn btn-ghost" onclick="resetFilters()">重置</button>
        <span class="count-badge" id="event-count"></span>
      </div>
      <div id="timeline-body"></div>
    </div>
    <div id="view-dashboard" class="view">
      <div class="page-title">總覽儀表板</div>
      <div class="page-sub">你的時光軸數據摘要</div>
      <div id="dashboard-body"></div>
    </div>
    <div id="view-console" class="view">
      <div class="page-title">AI 助理</div>
      <div class="page-sub">輸入 <code>/timeline</code>、<code>/analyze</code>、<code>/export</code> 或直接問我</div>
      <div class="console-wrap">
        <div class="console-log" id="console-log"></div>
        <div class="console-input-row">
          <textarea class="console-input" id="console-input"
            placeholder="/analyze  /timeline 2025 work  /export --public"
            onkeydown="consoleKeydown(event)"></textarea>
          <button class="btn btn-primary" onclick="consoleSend()">送出</button>
        </div>
      </div>
    </div>
  </main>
</div>
<script>
const API=(localStorage.getItem("livetime_api")||"http://127.0.0.1:8080").replace(/\\/$/,"");
const $=id=>document.getElementById(id);
async function apiFetch(path,opts={}){
  const res=await fetch(API+path,{headers:{"Content-Type":"application/json"},...opts});
  if(!res.ok){const e=await res.json().catch(()=>({detail:res.statusText}));throw new Error(e.detail||res.statusText);}
  return res.json();
}
function toast(msg,type="ok"){
  const el=document.createElement("div");el.className=`toast toast-${type}`;el.textContent=msg;
  $("toast-root").appendChild(el);setTimeout(()=>el.remove(),3500);
}
function showView(name,btn){
  document.querySelectorAll(".view").forEach(v=>v.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach(b=>b.classList.remove("active"));
  $(`view-${name}`).classList.add("active");btn.classList.add("active");
  if(name==="dashboard"&&!$("dashboard-body").dataset.loaded)loadDashboard();
}
const TYPE_COLOR={learn:"var(--t-learn)",work:"var(--t-work)",intern:"var(--t-intern)",job:"var(--t-job)",life:"var(--t-life)"};
const MOMENTUM_EMOJI={up:"⬆️",calm:"🌊",intense:"⚡"};
const MOMENTUM_COLOR={up:"rgba(52,227,168,.18)",calm:"rgba(90,209,255,.18)",intense:"rgba(255,200,97,.18)"};
const MOMENTUM_TEXT={up:"#34e3a8",calm:"#5ad1ff",intense:"#ffc861"};
function renderEvent(ev){
  const tb=TYPE_COLOR[ev.type]||"var(--a2)";
  const me=MOMENTUM_EMOJI[ev.momentum]||"";
  const mb=MOMENTUM_COLOR[ev.momentum]||"var(--bg-3)";
  const mt=MOMENTUM_TEXT[ev.momentum]||"var(--txt-2)";
  const tags=(ev.tags||[]).map(t=>`<span class="tag">${t}</span>`).join("");
  const link=ev.link?`<a class="event-link" href="https://${ev.link}" target="_blank">${ev.link}</a>`:"";
  return `<div class="event-card"><div class="event-dot"></div><div class="event-inner">
    <div class="event-meta">
      <span class="event-date">${ev.date_label}</span>
      <span class="type-badge" style="background:${tb}22;color:${tb};border:1px solid ${tb}44">${ev.type_label||ev.type}</span>
      ${ev.momentum?`<span class="momentum-badge" style="background:${mb};color:${mt}">${me} ${ev.momentum_label||ev.momentum}</span>`:""}
    </div>
    <div class="event-title">${ev.title}</div>
    <div class="event-desc">${ev.description||""}</div>
    ${tags?`<div class="tag-row">${tags}</div>`:""}
    ${link}
  </div></div>`;
}
function renderSkeletons(n=4){return Array.from({length:n},()=>`<div class="skeleton sk-card"></div>`).join("");}
async function loadTimeline(year,category,query){
  const body=$("timeline-body");body.innerHTML=renderSkeletons();
  try{
    let data;
    if(query&&query.length>0){
      const rows=await apiFetch(`/api/search?q=${encodeURIComponent(query)}&limit=50`);
      data={events:rows,total:rows.length};
    }else{
      const p=new URLSearchParams({limit:100});
      if(year)p.set("year",year);if(category)p.set("category",category);
      data=await apiFetch(`/api/events?${p}`);
    }
    $("event-count").textContent=`共 ${data.total} 筆`;
    if(data.events.length===0){body.innerHTML=`<div class="empty">找不到符合條件的事件</div>`;return;}
    body.innerHTML=`<div class="timeline-wrap"><div class="timeline-axis"></div>${data.events.map(renderEvent).join("")}</div>`;
  }catch(e){body.innerHTML=`<div class="empty">❌ 無法載入：${e.message}</div>`;toast(e.message,"err");}
}
function applyFilters(){
  loadTimeline($("filter-year").value||null,$("filter-cat").value||null,$("filter-search").value.trim()||null);
}
function resetFilters(){
  $("filter-year").value="";$("filter-cat").value="";$("filter-search").value="";
  loadTimeline(null,null,null);
}
let _t;function debounceSearch(){clearTimeout(_t);_t=setTimeout(applyFilters,380);}
async function loadDashboard(){
  const body=$("dashboard-body");body.innerHTML=renderSkeletons(3);
  try{
    const[s,sk,sr]=await Promise.all([apiFetch("/api/stats"),apiFetch("/api/skills"),apiFetch("/api/mood-series")]);
    const top=s.by_category[0]||{};
    body.innerHTML=`
    <div class="stats-grid">
      ${[["事件總數",s.total_events,"筆"],["最活躍分類",top.label||"-",""],
         ["情緒高點",Math.max(...sr.map(x=>x.mood)),"/100"],["技能種類",sk.length,"項"]]
        .map(([k,v,u])=>`<div class="card stat-card"><div class="stat-val">${v}</div>
          <div class="stat-label">${k}${u?`<span style="font-size:10px;color:var(--txt-3)"> ${u}</span>`:""}</div></div>`).join("")}
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px">
      <div class="card"><div class="section-title">技能雷達</div><div class="bar-chart">
        ${sk.map(x=>`<div class="bar-row"><span class="bar-label">${x.name}</span>
          <span class="bar-track"><span class="bar-fill" style="width:${x.value}%"></span></span>
          <span class="bar-val">${x.value}</span></div>`).join("")}
      </div></div>
      <div class="card"><div class="section-title">分類分布</div><div class="bar-chart">
        ${s.by_category.map(c=>`<div class="bar-row"><span class="bar-label">${c.label}</span>
          <span class="bar-track"><span class="bar-fill"
            style="width:${Math.round(c.count/s.total_events*100)}%;background:${TYPE_COLOR[c.type]||'var(--a1)'}"></span></span>
          <span class="bar-val">${c.count}</span></div>`).join("")}
      </div></div>
    </div>
    <div class="card" style="margin-top:18px"><div class="section-title">情緒 & 動能曲線</div>
      ${renderSparkline(sr)}</div>`;
    body.dataset.loaded="1";
  }catch(e){body.innerHTML=`<div class="empty">❌ 無法載入：${e.message}</div>`;toast(e.message,"err");}
}
function renderSparkline(series){
  if(!series.length)return"";
  const W=700,H=90,P=24;
  const xS=(W-P*2)/(series.length-1);
  const yS=v=>H-P-(v/100)*(H-P*2);
  const poly=(vals,color)=>`<polyline points="${vals.map((v,i)=>`${P+i*xS},${yS(v)}`).join(" ")}"
    fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>`;
  const dots=(vals,color)=>vals.map((v,i)=>`<circle cx="${P+i*xS}" cy="${yS(v)}" r="3" fill="${color}"/>`).join("");
  const labels=series.filter((_,i)=>i%2===0||i===series.length-1).map((_,ii)=>{
    const i=Math.min(ii*2,series.length-1);
    return`<text x="${P+i*xS}" y="${H-4}" text-anchor="middle" fill="var(--txt-3)" style="font-size:9px">${series[i].month}</text>`;
  }).join("");
  return`<div class="sparkline-wrap"><svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:${W}px">
    ${poly(series.map(s=>s.mood),"var(--a1)")}${dots(series.map(s=>s.mood),"var(--a1)")}
    ${poly(series.map(s=>s.prod),"var(--a2)")}${dots(series.map(s=>s.prod),"var(--a2)")}
    ${labels}</svg>
    <div style="display:flex;gap:16px;font-size:12px;color:var(--txt-3);margin-top:4px">
      <span><span style="width:12px;height:2px;background:var(--a1);display:inline-block"></span> 情緒</span>
      <span><span style="width:12px;height:2px;background:var(--a2);display:inline-block"></span> 動能</span>
    </div></div>`;
}
function appendMsg(role,text){
  const log=$("console-log");const div=document.createElement("div");
  div.className=`msg msg-${role}`;
  div.innerHTML=`<div class="msg-label">${role==="user"?"你":"🤖 時光機 AI"}</div><div class="bubble">${text}</div>`;
  log.appendChild(div);log.scrollTop=log.scrollHeight;return div;
}
async function consoleSend(){
  const input=$("console-input");const text=input.value.trim();if(!text)return;
  input.value="";appendMsg("user",escapeHtml(text));
  const w=appendMsg("ai",'<span class="loading-dots">思考中</span>');
  try{
    const data=await apiFetch("/api/chat",{method:"POST",body:JSON.stringify({message:text})});
    w.querySelector(".bubble").innerHTML=mdToHtml(data.reply);
  }catch(e){w.querySelector(".bubble").innerHTML=`❌ ${escapeHtml(e.message)}`;}
}
function consoleKeydown(e){if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();consoleSend();}}
function escapeHtml(s){return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");}
function mdToHtml(md){
  return escapeHtml(md)
    .replace(/```[\\w]*\\n?([\\s\\S]*?)```/g,(_,c)=>`<pre style="background:var(--bg);padding:10px;border-radius:8px;overflow:auto;font-size:12px;color:var(--a1)">${c}</pre>`)
    .replace(/`([^`]+)`/g,"<code style='background:var(--bg);padding:2px 5px;border-radius:4px;color:var(--a2)'>$1</code>")
    .replace(/\\*\\*(.+?)\\*\\*/g,"<strong>$1</strong>")
    .replace(/^#{1,3} (.+)$/gm,"<strong style='font-size:14px;color:var(--txt)'>$1</strong>")
    .replace(/^[-•] (.+)$/gm,"• $1")
    .replace(/\\n/g,"<br>");
}
async function checkApiStatus(){
  try{await apiFetch("/api/stats");$("api-status").textContent="後端已連線";$("api-status").style.color="var(--a1)";}
  catch{$("api-status").textContent="後端未連線";$("api-status").style.color="#f87171";}
}
checkApiStatus();
loadTimeline(null,null,null);
window.setApiUrl=url=>{localStorage.setItem("livetime_api",url);location.reload();};
</script>
</body>
</html>
"""


# ══════════════════════════════════════════════════════════════════════════════
# FILE MANIFEST
# (relative_path, content_variable, encoding)
# ══════════════════════════════════════════════════════════════════════════════

FILES = [
    ("backend/schema.sql",               SCHEMA_SQL,               "utf-8"),
    ("backend/requirements.txt",         REQUIREMENTS_TXT,         "utf-8"),
    ("backend/seed.py",                  SEED_PY,                  "utf-8"),
    ("backend/api_server.py",            API_SERVER_PY,            "utf-8"),
    ("backend/agent.py",                 AGENT_PY,                 "utf-8"),
    ("backend/agent_system_prompt.md",   AGENT_SYSTEM_PROMPT_MD,   "utf-8"),
    ("backend/mcp_server.py",            MCP_SERVER_PY,            "utf-8"),
    ("frontend/index.html",              INDEX_HTML,               "utf-8"),
]


# ══════════════════════════════════════════════════════════════════════════════
# SETUP LOGIC
# ══════════════════════════════════════════════════════════════════════════════

def main():
    # ── determine target root ──────────────────────────────────────────────
    if len(sys.argv) > 1:
        root = Path(sys.argv[1]).expanduser().resolve()
    else:
        root = Path.cwd() / "livetime-project"

    print(f"\n{BOLD}Livetime 時光機 — 一鍵建檔腳本{RST}\n")
    info(f"建立目標：{root}\n")

    # ── guard: don't overwrite an existing non-empty directory ────────────
    if root.exists() and any(root.iterdir()):
        warn(f"目錄 {root} 已存在且非空")
        answer = input("  是否繼續並覆蓋同名檔案？[y/N] ").strip().lower()
        if answer != "y":
            print("  已取消。")
            return

    # ── create directories ─────────────────────────────────────────────────
    dirs = sorted({(root / f).parent for f, _, _ in FILES})
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        info(f"mkdir  {d.relative_to(root)}/")

    print()

    # ── write files ────────────────────────────────────────────────────────
    for rel, content, enc in FILES:
        path = root / rel
        path.write_text(content, encoding=enc)
        size = path.stat().st_size
        ok(f"{'wrote':<6}  {rel:<42} ({size:,} bytes)")

    # ── write .gitignore ──────────────────────────────────────────────────
    gitignore = root / ".gitignore"
    gitignore.write_text("__pycache__/\n*.pyc\nbackend/livetime.db\n.env\n", encoding="utf-8")
    ok(f"{'wrote':<6}  .gitignore")

    # ── summary ────────────────────────────────────────────────────────────
    print(f"\n{G}{BOLD}✓ 所有檔案建立完成！{RST}\n")

    print(f"{BOLD}接下來的步驟：{RST}")
    print(f"""
  1. 進入專案目錄
     cd {root}

  2. 安裝 Python 依賴
     pip install -r backend/requirements.txt

  3. 初始化資料庫（只需執行一次）
     cd backend && python seed.py

  4. 啟動 REST API 後端
     python api_server.py
     # → http://127.0.0.1:8080
     # → 互動文件：http://127.0.0.1:8080/docs

  5. 開啟前端（新終端機）
     cd {root}/frontend
     python -m http.server 5500
     # → 瀏覽器開啟 http://localhost:5500

  6. （選用）啟用 AI 功能
     export ANTHROPIC_API_KEY=sk-ant-...
     # 重新啟動 api_server.py 後，AI 助理頁面即可使用

  7. （選用）ngrok 外網存取
     ngrok http 8080
     # 複製 https://xxx.ngrok-free.app 後在瀏覽器 console 執行：
     # setApiUrl("https://xxx.ngrok-free.app")
""")

    # ── auto-install prompt ────────────────────────────────────────────────
    answer = input("  是否立即安裝 Python 依賴套件？[y/N] ").strip().lower()
    if answer == "y":
        print()
        req = root / "backend" / "requirements.txt"
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req)],
            check=False,
        )
        if result.returncode == 0:
            ok("套件安裝完成\n")
        else:
            err("安裝途中發生錯誤，請手動執行 pip install -r backend/requirements.txt\n")

        # ── auto-seed prompt ───────────────────────────────────────────────
        answer2 = input("  是否立即初始化資料庫（seed）？[y/N] ").strip().lower()
        if answer2 == "y":
            import importlib.util, os
            old_dir = os.getcwd()
            os.chdir(root / "backend")
            spec = importlib.util.spec_from_file_location("seed", root / "backend" / "seed.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.seed()
            os.chdir(old_dir)


if __name__ == "__main__":
    main()
