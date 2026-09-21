"""MCP server: football fixtures, results, settlement and +EV price arithmetic.

Tools are deliberately split into two groups:
  * free-data tools (fixtures, results, settlement) — work for anyone, no key, no account
  * arithmetic tools (de-vig, EV, minimum odds, Kelly, parlay) — pure maths, no data at all
Plus an optional operator-only bridge to a private engine when SOCCER_ENGINE_PATH is set.
"""
from __future__ import annotations

import datetime
import json
from typing import Any

# The MCP Python SDK renamed FastMCP to MCPServer in v2. Support both so the server runs on either.
try:                                                        # mcp >= 2
    from mcp.server import MCPServer as _MCPServer
except ImportError:                                         # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _MCPServer

from . import __version__
from . import engine_bridge, math as odds_math, plugins, settlement, sources

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


def _error(message: str, **extra: Any) -> str:
    """Input problems come back as readable JSON, not as a stack trace.

    Without this an agent that passes "tomorrow" instead of a date got an MCP "unexpected exception"
    with the full Python traceback — useless to the caller and it leaks internals.
    """
    return _json({"error": message, **extra})


def _valid_date(value: Any) -> str | None:
    try:
        return datetime.date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError):
        return None


def _valid_price(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) > 1.0


def _valid_probability(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0.0 < float(value) < 1.0


@mcp.tool()
def get_fixtures(date: str, league: str | None = None, only_finished: bool = False) -> str:
    """All football fixtures of one day (YYYY-MM-DD) across every competition, with scores when played.

    Args:
        date: ISO date, e.g. 2026-09-20
        league: optional case-insensitive substring filter on the competition name
        only_finished: only return matches with a final score
    """
    if not (day := _valid_date(date)):
        return _error("date must be YYYY-MM-DD, e.g. 2026-09-20", got=date)
    events = sources.day_events(day)
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
    if not (day := _valid_date(date)):
        return _error("date must be YYYY-MM-DD, e.g. 2026-09-20", got=date)
    events = sources.day_events(day)
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

    if not isinstance(picks, list) or not picks:
        return _error("picks must be a non-empty list of {home, away, market, odds[, date]}")
    if date is not None and not _valid_date(date):
        return _error("date must be YYYY-MM-DD, e.g. 2026-09-20", got=date)
    supported = ", ".join(sorted(settlement.MARKETS))
    rows, staked, profit, wins = [], 0.0, 0.0, 0
    for pick in picks:
        market = str(pick.get("market") or "").upper().replace(" ", "")
        if market not in settlement.MARKETS:
            # Vorher blieb ein unbekannter Markt stillschweigend "unsettled" — der Aufrufer erfuhr nie,
            # dass "1" nicht existiert. Jetzt steht der Grund samt gültiger Liste in der Zeile.
            rows.append({**pick, "error": f"unknown market '{pick.get('market')}' — supported: {supported}"})
            continue
        if not _valid_price(pick.get("odds")):
            rows.append({**pick, "error": "odds must be a decimal price above 1.0"})
            continue
        day = pick.get("date") or date
        if not day:
            rows.append({**pick, "error": "no date given for this pick"})
            continue
        event, confidence = find(str(pick.get("home", "")), str(pick.get("away", "")), day)
        if not event:
            rows.append({**pick, "error": "no matching fixture found", "match_confidence": confidence})
            continue
        graded = settlement.outcome(market, event.get("home_score"), event.get("away_score"), pick.get("odds"))
        row = {
            "fixture": f'{event["home"]} vs {event["away"]}',
            "league": event.get("league"), "kickoff": event.get("kickoff"),
            "score": f'{event["home_score"]}:{event["away_score"]}',
            "market": market, "odds": pick.get("odds"),
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
def devig_market(prices: list[float], method: str = "power") -> str:
    """Strip the bookmaker margin from one market's prices and return the market's own probabilities.

    Uses the **power method**, which loads the margin onto the longshots the way bookmakers do —
    proportional de-vigging (`method="proportional"`) spreads it evenly and overstates them by
    around 1.5 percentage points on an 4.20 outsider.

    Args:
        prices: the decimal prices of all outcomes of the same market, e.g. [1.75, 3.6, 4.4] for 1X2
        method: "power" (default) or "proportional"
    """
    if not isinstance(prices, list) or len(prices) < 2:
        return _error("prices needs at least two prices of the same market, e.g. [1.75, 3.6, 4.4]")
    if not all(_valid_price(p) for p in prices):
        return _error("every price must be a decimal price above 1.0", got=prices)
    if method not in ("power", "proportional"):
        return _error("method must be 'power' or 'proportional'", got=method)
    return _json(odds_math.devig(prices, method))


@mcp.tool()
def evaluate_price(probability: float, odds: float, margin_pct: float = 3.0,
                   kelly_fraction: float = 0.25, tax_pct: float = 0.0) -> str:
    """Judge a price against your own probability: fair odds, EV, minimum odds and a scaled Kelly stake.

    Args:
        probability: your probability for the outcome, e.g. 0.55 (not 55)
        odds: the decimal price on offer, e.g. 1.90
        margin_pct: how much better than fair a price must be before you take it
        kelly_fraction: stake scaling; 0.25 means quarter Kelly
        tax_pct: share of the stake the book passes on (Germany: 0.053) — it comes off the payout,
            so it raises the minimum price and lowers the stake
    """
    if not _valid_probability(probability):
        return _error("probability must be between 0 and 1 (0.55, not 55)", got=probability)
    if not _valid_price(odds):
        return _error("odds must be a decimal price above 1.0", got=odds)
    if not isinstance(kelly_fraction, (int, float)) or not 0 < float(kelly_fraction) <= 1:
        return _error("kelly_fraction must be between 0 (exclusive) and 1, e.g. 0.25", got=kelly_fraction)
    result = odds_math.ev(probability, odds, tax_pct)
    result["minimum_odds"] = odds_math.minimum_odds(probability, margin_pct, tax_pct)
    result["stake"] = odds_math.kelly(probability, odds, kelly_fraction, tax_pct)
    result["take_it"] = odds >= result["minimum_odds"]["minimum_odds"]
    return _json(result)


@mcp.tool()
def parlay_math(legs: list[dict]) -> str:
    """Combined odds and EV of an accumulator, plus how fast the edge decays with each leg.

    Args:
        legs: e.g. [{"probability": 0.6, "odds": 1.8}, {"probability": 0.5, "odds": 2.0}]
    """
    if not isinstance(legs, list) or len(legs) < 2:
        return _error("legs needs at least two legs, each {probability, odds}")
    for i, leg in enumerate(legs, 1):
        if not isinstance(leg, dict) or not _valid_price(leg.get("odds")) or not _valid_probability(leg.get("probability")):
            return _error(f"leg {i} needs a decimal odds above 1.0 and a probability between 0 and 1", got=leg)
    return _json(odds_math.parlay(legs))


@mcp.tool()
def engine_status() -> str:
    """Report whether the optional private analysis engine and private plugins are wired up."""
    return _json({"engine": engine_bridge.available(), "plugins": LOADED_PLUGINS})


# Private tools attach here: see plugins.py. Empty in the public deployment.
LOADED_PLUGINS: list[str] = plugins.load(mcp)


def main() -> None:
    """Entry point: speaks MCP over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
