"""
agent.py — Livetime AI Agent
=============================
Slash-command parser + Anthropic API integration.
Connects to the local MCP server and routes /timeline, /analyze, /export.

Usage:
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

# ── MCP client (in-process, connects to the running mcp_server) ────────────
# We import the db helpers directly so the agent can run without a
# separate server process.  For a deployed setup, replace these calls
# with real MCP client tool-use requests.
from seed import get_conn

SYSTEM_PROMPT = (Path(__file__).parent / "agent_system_prompt.md").read_text(
    encoding="utf-8"
)

# ── Category aliases ────────────────────────────────────────────────────────
CATEGORY_ALIASES: dict[str, str] = {
    "學習": "learn", "learn": "learn",
    "作品": "work",  "work":  "work",
    "實習": "intern","intern":"intern",
    "工作": "job",   "job":   "job",
    "生活": "life",  "life":  "life",
}

MOMENTUM_EMOJI = {"up": "⬆️", "calm": "🌊", "intense": "⚡"}


# ── Inline DB helpers (mirror the MCP tools) ───────────────────────────────

def _fetch_events(
    year: int | None = None,
    category: str | None = None,
    momentum: str | None = None,
    tag: str | None = None,
    limit: int = 100,
    offset: int = 0,
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


def _fetch_mood_series() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM monthly_series ORDER BY yyyymm ASC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _fetch_skills() -> list[dict]:
    conn = get_conn()
    rows = conn.execute("SELECT name, value FROM skills ORDER BY value DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_summary_stats() -> dict:
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


# ── Slash-command renderers ────────────────────────────────────────────────

def render_timeline(year: int | None, category: str | None) -> str:
    """Build the Markdown timeline card output locally (no API call needed)."""
    result = _fetch_events(year=year, category=category)
    events = result["events"]
    total = result["total"]

    if not events:
        filter_desc = _filter_desc(year, category)
        return f"> 找不到符合條件的事件{filter_desc}。"

    lines: list[str] = []
    for ev in events:
        emoji = MOMENTUM_EMOJI.get(ev.get("momentum", ""), "")
        tags_str = " ".join(f"`{t}`" for t in ev.get("tags", []))
        link_line = f"🔗 [{ev['link']}]({ev['link']})" if ev.get("link") else ""
        block = [
            "---",
            f"### {ev['date_label']} · {ev.get('type_label', ev['type'])}",
            "",
            f"**{ev['title']}**",
            "",
            ev.get("description") or "",
            "",
            f"**情緒狀態**：{emoji} {ev.get('momentum_label', '')}",
            f"**技能標籤**：{tags_str}",
        ]
        if link_line:
            block.append(link_line)
        lines.extend(block)
        lines.append("")

    filter_desc = _filter_desc(year, category)
    lines.append(f"> 共 {total} 筆事件{filter_desc}")
    return "\n".join(lines)


def _filter_desc(year: int | None, category: str | None) -> str:
    parts = []
    if year:
        parts.append(f"{year} 年")
    if category:
        label = next(
            (v for k, v in {
                "learn":"學習","work":"作品","intern":"實習",
                "job":"工作","life":"生活"}.items() if k == category), category
        )
        parts.append(f"分類：{label}")
    return f"（{' · '.join(parts)}）" if parts else ""


# ── Claude API integration ─────────────────────────────────────────────────

def build_analyze_context() -> str:
    """Bundle all data into a text block for the /analyze prompt."""
    events = _fetch_events(limit=100)["events"]
    series = _fetch_mood_series()
    skills = _fetch_skills()
    stats = _get_summary_stats()

    ctx = {
        "summary_stats": stats,
        "events": [
            {k: v for k, v in e.items()
             if k in ("id","title","date_label","date_sort","type","type_label",
                      "momentum","momentum_label","description","tags")}
            for e in events
        ],
        "mood_series": series,
        "skills": skills,
    }
    return json.dumps(ctx, ensure_ascii=False, indent=2)


def build_export_context(public_only: bool) -> tuple[list[dict], dict]:
    """Return (events_for_export, meta)."""
    result = _fetch_events(limit=100)
    events = result["events"]
    if public_only:
        events = [e for e in events if e["type"] != "life"]

    category_counts: dict[str, int] = {}
    for e in events:
        category_counts[e["type"]] = category_counts.get(e["type"], 0) + 1

    meta = {"total": len(events), "categories": category_counts}
    return events, meta


# ── Command parser ─────────────────────────────────────────────────────────

def parse_slash(text: str) -> tuple[str, dict]:
    """
    Returns (command_name, kwargs).
    command_name is one of: 'timeline', 'analyze', 'export', 'unknown', 'chat'
    """
    text = text.strip()
    if not text.startswith("/"):
        return "chat", {"text": text}

    parts = text.split()
    cmd = parts[0].lstrip("/").lower()

    if cmd == "timeline":
        year, category = None, None
        for token in parts[1:]:
            if re.fullmatch(r"\d{4}", token):
                year = int(token)
            elif token.lower() in CATEGORY_ALIASES:
                category = CATEGORY_ALIASES[token.lower()]
        return "timeline", {"year": year, "category": category}

    if cmd == "analyze":
        return "analyze", {}

    if cmd == "export":
        public_only = "--public" in parts
        return "export", {"public_only": public_only}

    return "unknown", {"original": text}


UNKNOWN_HELP = """\
目前支援的指令：
• `/timeline [年份] [分類]` — 瀏覽時間軸
• `/analyze` — 深度洞察報告
• `/export [--public]` — 匯出作品集 JSON

輸入指令或直接用自然語言問我！"""


# ── Agent router ──────────────────────────────────────────────────────────

class LivetimeAgent:
    """Stateful agent: handles slash commands and passes chat to Claude."""

    def __init__(self, model: str = "claude-opus-4-8"):
        self.client = Anthropic()
        self.model = model
        self.history: list[dict] = []

    def chat(self, user_input: str) -> str:
        cmd, kwargs = parse_slash(user_input)

        # ── /timeline: pure local render, no API call ──────────────────────
        if cmd == "timeline":
            return render_timeline(kwargs["year"], kwargs["category"])

        # ── /unknown ───────────────────────────────────────────────────────
        if cmd == "unknown":
            return UNKNOWN_HELP

        # ── /analyze: attach data context, call Claude ─────────────────────
        if cmd == "analyze":
            context = build_analyze_context()
            injected = (
                "使用者輸入了 `/analyze`。\n\n"
                "以下是從資料庫取得的完整資料（JSON）：\n\n"
                f"```json\n{context}\n```\n\n"
                "請依照 System Prompt 的 `/analyze` 格式，生成完整的洞察報告。"
            )
            return self._ask_claude(injected, stateful=False)

        # ── /export: attach events, ask Claude to polish descriptions ──────
        if cmd == "export":
            public_only = kwargs["public_only"]
            events, meta = build_export_context(public_only)
            events_json = json.dumps(events, ensure_ascii=False, indent=2)
            injected = (
                f"使用者輸入了 `/export{'  --public' if public_only else ''}`。\n\n"
                "以下是從資料庫取得的事件資料：\n\n"
                f"```json\n{events_json}\n```\n\n"
                f"meta 資訊：{json.dumps(meta, ensure_ascii=False)}\n\n"
                f"exported_at: {date.today().isoformat()}\n"
                f"filter: {'public' if public_only else 'all'}\n\n"
                "請依照 System Prompt 的 `/export` 格式，對每筆事件的 description 進行潤飾，"
                "並輸出完整的 JSON 程式碼區塊。"
            )
            return self._ask_claude(injected, stateful=False)

        # ── natural language chat: stateful conversation ───────────────────
        if cmd == "chat":
            # Attach a mini context hint for data-related questions
            text = kwargs["text"]
            data_keywords = re.compile(
                r"事件|技能|心情|情緒|幾筆|做了什麼|分析|OKR|作品|實習|學習|工作|生活|Figma|Python|React",
                re.IGNORECASE,
            )
            if data_keywords.search(text):
                stats = _get_summary_stats()
                context_hint = (
                    f"\n\n[工具上下文] 統計摘要：{json.dumps(stats, ensure_ascii=False)}"
                )
                text = text + context_hint
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
            # keep last 20 turns to avoid context overflow
            self.history = self.history[-40:]
        return reply


# ── CLI entrypoint ────────────────────────────────────────────────────────

def main():
    agent = LivetimeAgent()

    # single-command mode: python agent.py "/timeline 2025"
    if len(sys.argv) > 1:
        user_input = " ".join(sys.argv[1:])
        print(agent.chat(user_input))
        return

    # interactive REPL
    print("時光機 AI 助理已啟動。輸入 /help 查看指令，Ctrl+C 離開。\n")
    while True:
        try:
            user_input = input("你：").strip()
            if not user_input:
                continue
            response = agent.chat(user_input)
            print(f"\n助理：\n{response}\n")
        except KeyboardInterrupt:
            print("\n掰掰！")
            break


if __name__ == "__main__":
    main()
