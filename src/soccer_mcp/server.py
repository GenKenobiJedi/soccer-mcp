"""MCP server: football fixtures, results, settlement and +EV price arithmetic.

Tools are deliberately split into two groups:
  * free-data tools (fixtures, results, settlement) — work for anyone, no key, no account
  * arithmetic tools (de-vig, EV, minimum odds, Kelly, parlay) — pure maths, no data at all
Plus an optional operator-only bridge to a private engine when SOCCER_ENGINE_PATH is set.
"""
from __future__ import annotations

import json
from typing import Any

# The MCP Python SDK renamed FastMCP to MCPServer in v2. Support both so the server runs on either.
try:                                                        # mcp >= 2
    from mcp.server import MCPServer as _MCPServer
except ImportError:                                         # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _MCPServer

from . import __version__
from . import engine_bridge, math as odds_math, settlement, sources

mcp = _MCPServer(
    "soccer-mcp",
    title="Soccer MCP",
    version=__version__,
    instructions=("Football fixtures and real results for any day, settlement of picks against the "
                  "final scoreline, and honest odds arithmetic (de-vig, EV, minimum odds, Kelly). "
                  "The arithmetic tools take your own probability — they never invent one."),
)


def _json(value: Any) -> str:
    """Tools return JSON text: the v1 server serialised return values itself, the v2 server does not,
    and a plain string result is what every MCP client can read."""
    return json.dumps(value, ensure_ascii=False, indent=1)


@mcp.tool()
def get_fixtures(date: str, league: str | None = None, only_finished: bool = False) -> str:
    """All football fixtures of one day (YYYY-MM-DD) across every competition, with scores when played.

    Args:
        date: ISO date, e.g. 2026-09-20
        league: optional case-insensitive substring filter on the competition name
        only_finished: only return matches with a final score
    """
    events = sources.day_events(date)
    if league:
        needle = league.lower()
        events = [e for e in events if needle in (e.get("league") or "").lower()]
    if only_finished:
        events = [e for e in events if e.get("finished")]
    return _json(events)


@mcp.tool()
def get_results(date: str, league: str | None = None) -> str:
    """Finished matches with final score for one day — the input for settling bets.

    Args:
        date: ISO date, e.g. 2026-09-20
        league: optional substring filter on the competition name
    """
    events = sources.day_events(date)
    out = [e for e in events if e.get("finished") and e.get("home_score") is not None]
    if league:
        needle = league.lower()
        out = [e for e in out if needle in (e.get("league") or "").lower()]
    return _json(sorted(out, key=lambda e: (e.get("league") or "", e.get("home") or "")))


@mcp.tool()
def settle_picks(picks: list[dict], date: str | None = None) -> str:
    """Settle a list of picks against the real scorelines and return per-pick results plus totals.

    Each pick: {"home": "...", "away": "...", "market": "O2.5", "odds": 1.75, "date": "2026-09-20"}
    Supported markets: O/U lines (1.0-4.5, quarter lines included), BTTS, 1X2, 2X2, DC.
    Team names are matched fuzzily against the day's fixtures, so slight spelling differences are fine.

    Args:
        picks: list of picks, each needing home, away, market and odds
        date: fallback ISO date when a pick carries no date of its own
    """
    import datetime
    import difflib
    import unicodedata

    def norm(value: str) -> str:
        value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()
        return " ".join(value.replace("-", " ").replace(".", " ").split())

    def find(home: str, away: str, day: str):
        best, score = None, 0.0
        base = datetime.date.fromisoformat(day)
        for delta in (-1, 0, 1):
            for event in sources.day_events((base + datetime.timedelta(days=delta)).isoformat()):
                if not event.get("finished"):
                    continue
                s1 = difflib.SequenceMatcher(None, norm(home), norm(event["home"])).ratio()
                s2 = difflib.SequenceMatcher(None, norm(away), norm(event["away"])).ratio()
                combined = (s1 + s2) / 2
                if combined > score:
                    best, score = event, combined
        return (best, round(score, 3)) if best and score >= 0.6 else (None, round(score, 3))

    rows, staked, profit, wins = [], 0.0, 0.0, 0
    for pick in picks:
        day = pick.get("date") or date
        if not day:
            rows.append({**pick, "error": "no date given for this pick"})
            continue
        event, confidence = find(str(pick.get("home", "")), str(pick.get("away", "")), day)
        if not event:
            rows.append({**pick, "error": "no matching fixture found", "match_confidence": confidence})
            continue
        graded = settlement.outcome(pick.get("market"), event.get("home_score"), event.get("away_score"), pick.get("odds"))
        row = {
            "fixture": f'{event["home"]} vs {event["away"]}',
            "league": event.get("league"), "kickoff": event.get("kickoff"),
            "score": f'{event["home_score"]}:{event["away_score"]}',
            "market": pick.get("market"), "odds": pick.get("odds"),
            "match_confidence": confidence,
        }
        if graded:
            row.update(graded)
            staked += 1.0
            profit += graded["profit"]
            wins += 1 if graded["result"] in ("win", "halfwin") else 0
        rows.append(row)
    settled = [r for r in rows if r.get("result")]
    return _json({
        "picks": rows,
        "summary": {
            "picks": len(picks), "settled": len(settled), "unsettled": len(picks) - len(settled),
            "wins": wins,
            "hit_rate_pct": round(wins / len(settled) * 100, 1) if settled else None,
            "staked_units": staked,
            "profit_units": round(profit, 3),
            "roi_pct": round(profit / staked * 100, 2) if staked else None,
        },
        "note": "One unit per pick, priced at the odds you quoted. ROI on a handful of picks proves nothing.",
    })


@mcp.tool()
def devig_market(prices: list[float]) -> str:
    """Strip the bookmaker margin from one market's prices and return the market's own probabilities.

    Args:
        prices: the decimal prices of all outcomes of the same market, e.g. [1.75, 3.6, 4.4] for 1X2
    """
    return _json(odds_math.devig(prices))


@mcp.tool()
def evaluate_price(probability: float, odds: float, margin_pct: float = 3.0, kelly_fraction: float = 0.25) -> str:
    """Judge a price against your own probability: fair odds, EV, minimum odds and a scaled Kelly stake.

    Args:
        probability: your probability for the outcome, e.g. 0.55 (not 55)
        odds: the decimal price on offer, e.g. 1.90
        margin_pct: how much better than fair a price must be before you take it
        kelly_fraction: stake scaling; 0.25 means quarter Kelly
    """
    result = odds_math.ev(probability, odds)
    result["minimum_odds"] = odds_math.minimum_odds(probability, margin_pct)
    result["stake"] = odds_math.kelly(probability, odds, kelly_fraction)
    result["take_it"] = odds >= result["minimum_odds"]["minimum_odds"]
    return _json(result)


@mcp.tool()
def parlay_math(legs: list[dict]) -> str:
    """Combined odds and EV of an accumulator, plus how fast the edge decays with each leg.

    Args:
        legs: e.g. [{"probability": 0.6, "odds": 1.8}, {"probability": 0.5, "odds": 2.0}]
    """
    return _json(odds_math.parlay(legs))


@mcp.tool()
def engine_status() -> str:
    """Report whether the optional private analysis engine is wired up (operator deployments only)."""
    return _json(engine_bridge.available())


def main() -> None:
    """Entry point: speaks MCP over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
