"""ESPN day scoreboard — every competition of one day in a single call.

Why this host: the standard ESPN host (site.api.espn.com) answers the "all soccer" scoreboard with
Access Denied from many servers, while site.web.api.espn.com returns the same payload with HTTP 200.
Requests must go out WITHOUT a custom User-Agent: ESPN answers 403 to every custom UA and 200 to the
default one. Date ranges (dates=A-B) are rejected with HTTP 400, so we fetch one day per call and
cache it on disk.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import time
import urllib.request

BASE = "https://site.web.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard?dates={day}&limit=1000"
UID_LEAGUE = re.compile(r"~l:(\d+)~")
CACHE_DIR = pathlib.Path(os.environ.get("SOCCER_MCP_CACHE", pathlib.Path.home() / ".cache/soccer-mcp"))
TTL = int(os.environ.get("SOCCER_MCP_TTL", "900"))            # seconds; finished days never change
FINISHED_DAY_TTL = int(os.environ.get("SOCCER_MCP_FINISHED_TTL", "604800"))


def _cache_path(day: str) -> pathlib.Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"day-{day}.json"


def _fetch(day: str) -> dict:
    compact = day.replace("-", "")
    req = urllib.request.Request(BASE.format(day=compact), headers={"Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=45) as r:          # no custom UA — see module docstring
        return json.loads(r.read().decode("utf-8"))


def day_events(day: str, ttl: int | None = None) -> list[dict]:
    """Normalised fixtures for one ISO date (YYYY-MM-DD)."""
    path = _cache_path(day)
    if path.exists():
        age = time.time() - path.stat().st_mtime
        limit = ttl if ttl is not None else (FINISHED_DAY_TTL if day < time.strftime("%Y-%m-%d") else TTL)
        if age < limit:
            return json.loads(path.read_text() or "[]")
    try:
        data = _fetch(day)
    except Exception as exc:                                     # network/parse problems stay visible
        if path.exists():
            return json.loads(path.read_text() or "[]")
        raise RuntimeError(f"ESPN scoreboard fetch failed for {day}: {exc}") from exc
    events = _parse(data)
    path.write_text(json.dumps(events, ensure_ascii=False))
    return events


def _parse(data: dict) -> list[dict]:
    from .leagues import league_map                     # local import: keeps the fetch path dependency-free
    known = league_map()
    out = []
    for ev in data.get("events") or []:
        comp = (ev.get("competitions") or [{}])[0]
        competitors = comp.get("competitors") or []
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        status = ((comp.get("status") or {}).get("type") or {})
        match = UID_LEAGUE.search(str(ev.get("uid") or ""))
        league_id = match.group(1) if match else None
        league = (known.get(league_id or "") or {}).get("name", "")
        out.append({
            "date": (ev.get("date") or "")[:10],
            "kickoff": ev.get("date"),
            "home": ((home.get("team") or {}).get("displayName") or "").strip(),
            "away": ((away.get("team") or {}).get("displayName") or "").strip(),
            "home_score": _int(home.get("score")),
            "away_score": _int(away.get("score")),
            "league": league,
            "league_id": league_id,
            "finished": bool(status.get("completed")),
            "status": status.get("detail") or status.get("description") or "",
        })
    return out


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
