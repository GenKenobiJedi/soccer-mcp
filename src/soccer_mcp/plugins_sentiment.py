"""Team-Sentiment plugin für soccer-mcp: holt Team-Mood-Karten vom VPS-Dashboard.

Ein Tool: `get_team_sentiment(date, teams?)` — liest `GET /api/team-sentiment`
von der Soccer-Betting-Engine (Burhans VPS). Der Zugriff braucht das Dashboard-Token
(SOCCER_SENTIMENT_URL + SOCCER_SENTIMENT_TOKEN Umgebungsvariablen im actor.json).
Fällt der Endpoint aus, antwortet das Tool mit {'ok': False, 'error': ...} und dem
Hinweis, dass der Client es später erneut versuchen soll. Der Actor lädt keinen
News-Cache mit — die Datenkraft lebt auf dem VPS-Backend.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import urllib.request


def _json_err(msg: str) -> str:
    """Error-JSON (module-level, von register und Inneren genutzt)."""
    return json.dumps({"ok": False, "error": msg}, ensure_ascii=False)


def register(server) -> None:
    import soccer_mcp.server as _srv  # noqa: F401  (Attribut-Alias für den Actor-Dispatcher)

    @server.tool()
    def get_team_sentiment(date: str | None = None, teams: list[str] | None = None) -> str:
        """News-sentiment per team (krypto-style team mood): net score -1..+1, level
        (rot/gelb/gruen), trend, hard absences, factor list with sources.

        Args:
            date: ISO date (YYYY-MM-DD). Default: today (UTC).
            teams: optional list — return only teams whose name contains one of these
                   substrings (case-insensitive), e.g. ["Bayern", "Union"].
        """
        base = os.environ.get("SOCCER_SENTIMENT_URL", "").rstrip("/")
        token = os.environ.get("SOCCER_SENTIMENT_TOKEN", "")
        if not base:
            return _json_err("sentiment backend not configured (SOCCER_SENTIMENT_URL missing)")
        day = date or dt.date.today().isoformat()
        url = f"{base}/api/team-sentiment?date={day}"
        req = urllib.request.Request(url)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                doc = json.loads(resp.read().decode())
        except Exception as exc:
            return _json_err(f"backend unreachable: {type(exc).__name__}: {exc}")
        if doc.get("error"):
            return _json_err(f"backend error: {doc['error']}")

        all_teams = doc.get("teams") or []
        out_teams = all_teams
        if teams:
            needles = [t.lower() for t in teams]
            out_teams = [t for t in out_teams if any(n in (t.get("team") or "").lower() for n in needles)]
        # Karten passend zu den gefilterten Teams
        by_team = {(t.get("team") or "").lower(): c for t, c in zip(all_teams, doc.get("cards") or [])}
        cards = [by_team.get((t.get("team") or "").lower(), "") for t in out_teams]
        return json.dumps({
            "ok": True,
            "date": doc.get("date") or day,
            "teams": out_teams,
            "cards": cards,
        }, ensure_ascii=False)

    # Actor-Dispatcher ruft tools als Modul-Attribut — Alias setzen:
    _srv.get_team_sentiment = get_team_sentiment
