"""ESPN day scoreboard — every competition of one day in a single call.

Why this host: the standard ESPN host (site.api.espn.com) answers the "all soccer" scoreboard with
Access Denied from many servers, while site.web.api.espn.com returns the same payload with HTTP 200.
Requests must go out WITHOUT a custom User-Agent: ESPN answers 403 to every custom UA and 200 to the
default one. Date ranges (dates=A-B) are rejected with HTTP 400, so we fetch one day per call and
cache it on disk.

Freshness contract: a past day is NOT simply frozen for a week — a day cached while its matches were
still running would otherwise serve a "live" snapshot long after full time. A past day only gets the
long FINISHED_DAY_TTL once every cached event carries a final score; until then it refreshes on the
short TTL. Every served row carries `source` and a `provenance` block — fetched_at, its basis
(upstream fetch vs cache mtime), cache_status (miss|hit|refresh|stale) and fetch_error — so a
cache-served or stale answer is disclosed instead of looking freshly fetched. A corrupt cache is
never served: it refetches, and it is never handed out as a fallback.
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import re
import time
import urllib.request

BASE = "https://site.web.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard?dates={day}&limit=1000"
UID_LEAGUE = re.compile(r"~l:(\d+)~")
CACHE_DIR = pathlib.Path(os.environ.get("SOCCER_MCP_CACHE", pathlib.Path.home() / ".cache/soccer-mcp"))
TTL = int(os.environ.get("SOCCER_MCP_TTL", "900"))            # seconds; unfinished days must refresh
FINISHED_DAY_TTL = int(os.environ.get("SOCCER_MCP_FINISHED_TTL", "604800"))

SOURCE = "ESPN"
BASIS_UPSTREAM = "upstream"
BASIS_CACHE_MTIME = "cache_mtime"


def _cache_path(day: str) -> pathlib.Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"day-{day}.json"


def _fetch(day: str) -> dict:
    compact = day.replace("-", "")
    req = urllib.request.Request(BASE.format(day=compact), headers={"Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=45) as r:          # no custom UA — see module docstring
        return json.loads(r.read().decode("utf-8"))


def _iso(timestamp: float) -> str:
    return datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc).isoformat()


def _provenance(status: str, fetched_at: str, basis: str, *,
                stale: bool = False, error: str | None = None) -> dict:
    return {"fetched_at": fetched_at, "fetched_at_basis": basis,
            "cache_status": status, "stale": stale, "fetch_error": error}


def _annotate(rows: list[dict], provenance: dict) -> list[dict]:
    return [{**row, "source": SOURCE, "provenance": dict(provenance)} for row in rows]


def _hit_provenance(row: dict, mtime: float) -> dict:
    """Keep the recorded fetch time on a hit; a legacy row discloses the cache mtime instead."""
    recorded = row.get("provenance")
    if isinstance(recorded, dict) and recorded.get("fetched_at"):
        return {**recorded, "cache_status": "hit", "stale": False}
    return _provenance("hit", _iso(mtime), BASIS_CACHE_MTIME)


def _stale_provenance(row: dict, mtime: float, error: str) -> dict:
    recorded = row.get("provenance") if isinstance(row, dict) else None
    if isinstance(recorded, dict) and recorded.get("fetched_at"):
        return {**recorded, "cache_status": "stale", "stale": True, "fetch_error": error}
    return _provenance("stale", _iso(mtime), BASIS_CACHE_MTIME, stale=True, error=error)


def _read_cache(path: pathlib.Path) -> list[dict] | None:
    """The cached day, or None when the file is missing, unreadable or not the expected shape.

    A half-written or foreign cache must refetch rather than propagate, and must never be handed
    out later as a fallback — that would make a broken file look like real data.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, ValueError):                                # includes UnicodeDecodeError
        return None
    if not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    if not all(isinstance(event, dict) and isinstance(event.get("finished"), bool) for event in data):
        return None
    return data


def _is_finished_day(rows: list[dict]) -> bool:
    """Frozen for the long TTL only when every event is final *with a scoreline* — "finished" without
    a score is an artefact, and a day that still holds postponed/cancelled events keeps refreshing."""
    return bool(rows) and all(
        event.get("finished") is True
        and event.get("home_score") is not None and event.get("away_score") is not None
        for event in rows
    )


def day_events(day: str, ttl: int | None = None) -> list[dict]:
    """Normalised fixtures for one ISO date (YYYY-MM-DD)."""
    path = _cache_path(day)
    cached = _read_cache(path)
    mtime = path.stat().st_mtime if cached is not None else 0.0
    if cached is not None:
        age = time.time() - mtime
        limit = ttl if ttl is not None else (
            FINISHED_DAY_TTL if day < time.strftime("%Y-%m-%d") and _is_finished_day(cached) else TTL
        )
        if limit > 0 and age < limit:
            return [{**row, "source": SOURCE, "provenance": _hit_provenance(row, mtime)}
                    for row in cached]
    try:
        data = _fetch(day)
        events = _parse(data)
    except Exception as exc:                                     # network/parse problems stay visible
        if cached:
            error = f"{type(exc).__name__}: {exc}"
            return [{**row, "source": SOURCE, "provenance": _stale_provenance(row, mtime, error)}
                    for row in cached]
        raise RuntimeError(f"ESPN scoreboard fetch failed for {day}: {exc}") from exc
    status = "refresh" if cached is not None else "miss"
    stamped = _annotate(events, _provenance(status, _iso(time.time()), BASIS_UPSTREAM))
    path.write_text(json.dumps(stamped, ensure_ascii=False), encoding="utf-8")
    return stamped


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
