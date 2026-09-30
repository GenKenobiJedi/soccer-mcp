"""MCP server: football fixtures, results, settlement and +EV price arithmetic.

Tools are deliberately split into two groups:
  * free-data tools (fixtures, results, settlement) — work for anyone, no key, no account
  * arithmetic tools (de-vig, EV, minimum odds, Kelly, parlay) — pure maths, no data at all
Plus an optional operator-only bridge to a private engine when SOCCER_ENGINE_PATH is set.
"""
from __future__ import annotations

import datetime
import json
import re
from typing import Annotated, Any

# The MCP Python SDK renamed FastMCP to MCPServer in v2. Support both so the server runs on either.
try:                                                        # mcp >= 2
    from mcp.server import MCPServer as _MCPServer
    from mcp.types import ToolAnnotations
except ImportError:                                         # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _MCPServer
    from mcp.types import ToolAnnotations

from pydantic import Field
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


def _error(message: str, **extra: Any) -> dict[str, Any]:
    """Input problems come back as a readable dict, not as a stack trace.

    Without this an agent that passes "tomorrow" instead of a date got an MCP "unexpected exception"
    with the full Python traceback — useless to the caller and it leaks internals.
    """
    return {"error": message, **extra}


def _valid_date(value: Any) -> str | None:
    try:
        return datetime.date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError):
        return None


def _valid_price(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and float(value) > 1.0


def _valid_probability(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0.0 < float(value) < 1.0


# Youth, reserve and second-team markers as they appear in the fixture feed. A bare nickname
# ("Ajax") must never resolve to one of these when the senior side is also in the window.
# Token-based, not substring: "Tottenham" contains "ham" and "Amsterdam" contains "am", so
# short markers like "am"/"b"/"ii" must match whole words only.
_RESERVE_TOKENS = frozenset({
    "u16", "u17", "u18", "u19", "u20", "u21", "u23", "u25",      # youth age grades
    "amateurs", "academy", "reserves", "reserve", "youth",       # generic
    "ii", "iii", "iv", "b", "castilla", "primavera", "baby",     # named second sides
    "women", "w", "next", "sv", "am", "cfc", "sc", "ats", "as",
})


def _is_youth_or_reserve(name: str) -> bool:
    tokens = re.split(r"[^a-z0-9]+", (name or "").lower())
    return any(t in _RESERVE_TOKENS for t in tokens if t)


# Nicknames and short forms that no amount of string similarity can recover: "man united" is
# 0.74 similar to "ayr united", and "bvb" is not a substring of "borussia dortmund".
ALIASES: dict[str, str] = {
    "man utd": "manchester united",
    "man united": "manchester united",
    "man u": "manchester united",
    "mufc": "manchester united",
    "mancunited": "manchester united",
    "bvb": "borussia dortmund",
    "bvb 09": "borussia dortmund",
    "dortmund": "borussia dortmund",
    "bayern": "bayern munich",
    "bayern munchen": "bayern munich",
    "fc bayern": "bayern munich",
    "ajax": "ajax amsterdam",
    "psv": "psv eindhoven",
    "atalanta bc": "atalanta",
    "inter": "internazionale",
    "inter milano": "internazionale",
    "ac milan": "milan",
    "juve": "juventus",
    "real": "real madrid",
    "atletico": "atletico madrid",
    "atleti": "atletico madrid",
    "spurs": "tottenham hotspur",
    "hotspur": "tottenham hotspur",
    "wolves": "wolverhampton wanderers",
    "newcastle": "newcastle united",
    "newcastle utd": "newcastle united",
    "leeds": "leeds united",
    "nottm": "nottingham forest",
    "forest": "nottingham forest",
    "celtic": "celtic",
    "rangers": "rangers",
    "olympiacos": "olympiacos",
    "fenerbahce": "fenerbahce",
    "galatasaray": "galatasaray",
    "besiktas": "besiktas",
    "liverpool fc": "liverpool",
    "city": "manchester city",
    "mcfc": "manchester city",
}


def _tool(annotations: ToolAnnotations | None = None, **kwargs: Any):
    """Decorator um @mcp.tool() für dieSmithery-Gütekriterien:
      * explizite ToolAnnotationen (readOnlyHint etc.),
      * structured output via return-annotation.
    Jedes Tool holt hier dieselbe Basiskonfiguration, statt siebenmal boilerplate."""
    return mcp.tool(annotations=annotations, structured_output=True, **kwargs)


ReadTool = ToolAnnotations(title="Read data", read_only_hint=True, destructive_hint=False, idempotent_hint=False)
MathTool = ToolAnnotations(title="Pure computation", read_only_hint=True, destructive_hint=False, idempotent_hint=True)


@_tool(ReadTool)
def get_fixtures(
    date: Annotated[str, Field(description="ISO date like 2026-09-20, the day to list fixtures for")],
    league: Annotated[str | None, Field(description="optional case-insensitive substring filter on the competition name, e.g. 'bundesliga'")] = None,
    only_finished: Annotated[bool, Field(description="true = only matches with a final score")] = False,
) -> list[dict[str, Any]]:
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
    return (events)


@_tool(ReadTool)
def get_results(
    date: Annotated[str, Field(description="ISO date like 2026-09-20, the day to read final scores for")],
    league: Annotated[str | None, Field(description="optional case-insensitive substring filter on the competition name")] = None,
) -> list[dict[str, Any]]:
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
    return (sorted(out, key=lambda e: (e.get("league") or "", e.get("home") or "")))


@_tool(ReadTool)
def settle_picks(
    picks: Annotated[list[dict], Field(description="list of picks, each {home, away, market, odds[, date]}; market like 'O2.5', 'BTTS', '1X2'")],
    date: Annotated[str | None, Field(description="fallback ISO date for picks that carry no date of their own")] = None,
) -> dict[str, Any]:
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
    return ({
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


@_tool(MathTool)
def devig_market(
    prices: Annotated[list[float], Field(description="all decimal prices of ONE market, e.g. [1.75, 3.6, 4.4] for 1X2")],
    method: Annotated[str, Field(description="'power' (default, loads margin onto longshots) or 'proportional'")] = "power",
) -> dict[str, Any]:
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
    return (odds_math.devig(prices, method))


@_tool(MathTool)
def evaluate_price(
    probability: Annotated[float, Field(description="your win probability for the outcome, 0.55 not 55")],
    odds: Annotated[float, Field(description="the decimal price on offer, e.g. 1.90")],
    margin_pct: Annotated[float, Field(description="required edge in % before you take the price")] = 3.0,
    kelly_fraction: Annotated[float, Field(description="Kelly scaling, 0.25 = quarter Kelly")] = 0.25,
    tax_pct: Annotated[float, Field(description="share of stake the book passes on, e.g. 0.053 for Germany")] = 0.0,
) -> dict[str, Any]:
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
    return (result)


@_tool(MathTool)
def parlay_math(
    legs: Annotated[list[dict], Field(description="at least two legs, each {probability, odds} e.g. [{\"probability\":0.6,\"odds\":1.8}]")],
) -> dict[str, Any]:
    """Combined odds and EV of an accumulator, plus how fast the edge decays with each leg.

    Args:
        legs: e.g. [{"probability": 0.6, "odds": 1.8}, {"probability": 0.5, "odds": 2.0}]
    """
    if not isinstance(legs, list) or len(legs) < 2:
        return _error("legs needs at least two legs, each {probability, odds}")
    for i, leg in enumerate(legs, 1):
        if not isinstance(leg, dict) or not _valid_price(leg.get("odds")) or not _valid_probability(leg.get("probability")):
            return _error(f"leg {i} needs a decimal odds above 1.0 and a probability between 0 and 1", got=leg)
    return (odds_math.parlay(legs))


@_tool(ReadTool)
def engine_status() -> dict[str, Any]:
    """Report whether the optional private analysis engine and private plugins are wired up."""
    return ({"engine": engine_bridge.available(), "plugins": LOADED_PLUGINS})


# Private tools attach here: see plugins.py. Empty in the public deployment.
LOADED_PLUGINS: list[str] = plugins.load(mcp)


@_tool(ReadTool)
def get_team_form(
    team: Annotated[str, Field(description="team name, matched fuzzily against the fixtures, e.g. 'Bayern Munich'")],
    lookback_days: Annotated[int, Field(description="how many days back to read results, e.g. 60", ge=7, le=365)] = 60,
    h2h_against: Annotated[str | None, Field(description="optional second team: returns the head-to-head meetings in the window too")] = None,
) -> dict[str, Any]:
    """Recent form of one team from real final scores: W/D/L, goals, per-match list, and optional head-to-head.

    This is the one call an agent needs before it prices anything: form is the only team input that
    can be read from public data without a paid provider.

    Args:
        team: team name, matched fuzzily, e.g. "Bayern Munich"
        lookback_days: window in days, 7-365 (default 60)
        h2h_against: optional second team, adds their meetings in the same window
    """
    import difflib
    import unicodedata

    def norm(value: str) -> str:
        value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()
        return " ".join(value.replace("-", " ").replace(".", " ").split())

    needle = norm(team)
    if not needle:
        return _error("team must be a non-empty name", got=team)

    today = datetime.date.today()
    start = today - datetime.timedelta(days=int(lookback_days))
    rows: list[dict[str, Any]] = []
    names: set[str] = set()
    day = start
    while day <= today:
        for e in sources.day_events(day.isoformat()):
            if not e.get("finished") or e.get("home_score") is None:
                continue
            rows.append(e)
            names.add(e.get("home") or "")
            names.add(e.get("away") or "")
        day += datetime.timedelta(days=1)

    def match(candidate: str) -> tuple[str | None, list[str]]:
        """Resolve a typed club name to a canonical one in this window.

        Returns (name, alternatives). `name` is None when nothing matched; `alternatives` is
        non-empty when the input is genuinely ambiguous and the caller must ask, not guess.
        """
        if not candidate:
            return None, []
        c = norm(candidate)
        pool = [n for n in names if n]

        # 1. exact hit on a known name -> canonical spelling, always safe
        for n in pool:
            if norm(n) == c:
                return n, []

        # 2. known nickname. "Man United" and "BVB" are not fuzzy-derivable, but the nickname
        #    must land on exactly ONE club: "Barcelona" is also "Barcelona B" and "Barcelona SC".
        alias = ALIASES.get(c)
        if alias:
            hits = [n for n in pool if norm(n) == alias or norm(n).startswith(alias + " ")]
            # "Real" is Real Madrid plus Castilla/U19/III, "Spurs" is the first team plus its U21.
            # That is a league tier, not a real ambiguity: the senior side is the only sensible
            # reading, and refusing to answer "Real Madrid" over its own youth teams is useless.
            senior = [n for n in hits if not _is_youth_or_reserve(n)]
            if len(senior) == 1:
                return senior[0], []
            if len(senior) > 1:
                return None, sorted(senior)
            if len(hits) == 1:
                return hits[0], []

        # 3. prefix: "Bayern" -> "Bayern Munich". difflib alone scores that 0.63 and misses it at
        #    any sane cutoff, and a short club name is how humans actually type. But bare
        #    "Ajax" is also "Ajax Amsterdam" and "AFC Ajax Amateurs", so >1 candidate asks.
        prefix = [n for n in pool if norm(n).startswith(c + " ")]
        if len(prefix) == 1:
            return prefix[0], []
        if len(prefix) > 1:
            # prefer the senior side, then the shortest name
            senior = [n for n in prefix if not _is_youth_or_reserve(n)]
            if len(senior) == 1:
                return senior[0], []
            return None, sorted(prefix)

        # 4. fuzzy, e.g. "Man Utd" -> "Manchester United"
        close = difflib.get_close_matches(c, [norm(n) for n in pool], n=1, cutoff=0.75)
        if close:
            inverse = {norm(n): n for n in pool}
            return inverse.get(close[0]), []
        return None, []

    def match_other(candidate: str) -> str | None:
        """Same resolution, but never onto `found` itself: h2h_against must name a second club,
        and resolving it onto the first would silently report 0 meetings instead of a name error."""
        hit, _ = match(candidate)
        if hit and hit != found:
            return hit
        # played in the window but not in the finished-results set: accept a close fixture name
        needle2 = norm(candidate or "")
        names_any = {e.get("home") for e in rows if e.get("home")} | {e.get("away") for e in rows if e.get("away")}
        for n in names_any:
            if n != found and norm(n) == needle2:
                return n
        close = difflib.get_close_matches(needle2, [norm(n or "") for n in names_any], n=1, cutoff=0.8)
        if close:
            inverse = {norm(n): n for n in names_any}
            found2 = inverse.get(close[0])
            if found2 and found2 != found:
                return found2
        return None

    found, alternatives = match(team)
    if not found:
        if alternatives:
            # Guessing a league tier would poison every downstream number, so ask instead.
            return _error(f"{team!r} is ambiguous in the last {lookback_days} days", ambiguous=team,
                          did_you_mean=alternatives, hint="pass the full club name")
        return _error(f"no team close to {team!r} in the last {lookback_days} days", known_sample=sorted(names)[:15])

    played: list[dict[str, Any]] = []
    for e in rows:
        if e.get("home") != found and e.get("away") != found:
            continue
        home_is_ours = e.get("home") == found
        gf = e.get("home_score") if home_is_ours else e.get("away_score")
        ga = e.get("away_score") if home_is_ours else e.get("home_score")
        gf, ga = int(gf or 0), int(ga or 0)
        played.append({
            "date": e.get("date"), "league": e.get("league"),
            "home": e.get("home"), "away": e.get("away"),
            "score": f"{e.get('home_score')}-{e.get('away_score')}",
            "venue": "home" if home_is_ours else "away",
            "goals_for": gf, "goals_against": ga,
            "result": "W" if gf > ga else ("D" if gf == ga else "L"),
        })
    played.sort(key=lambda m: m.get("date") or "", reverse=True)

    wins = sum(1 for m in played if m["result"] == "W")
    draws = sum(1 for m in played if m["result"] == "D")
    losses = sum(1 for m in played if m["result"] == "L")
    n = len(played) or 1
    result: dict[str, Any] = {
        "team": found,
        "lookback_days": int(lookback_days),
        "matches": len(played),
        "record": {"W": wins, "D": draws, "L": losses},
        "goals_for": sum(m["goals_for"] for m in played),
        "goals_against": sum(m["goals_against"] for m in played),
        "goals_per_game": round(sum(m["goals_for"] for m in played) / n, 2),
        "conceded_per_game": round(sum(m["goals_against"] for m in played) / n, 2),
        "win_rate_pct": round(wins / n * 100, 1),
        "clean_sheets": sum(1 for m in played if m["goals_against"] == 0),
        "form_string": "".join(m["result"] for m in played[:10]),
        "results": played[:20],
    }

    if h2h_against:
        other = match_other(h2h_against)
        if not other:
            result["head_to_head"] = _error(
                f"no second team close to {h2h_against!r} in the last {lookback_days} days",
                resolved_team=found, known_sample=sorted(names)[:10])
        else:
            pair = {found, other}
            meetings = [e for e in rows if {e.get("home"), e.get("away")} == pair]
            meetings.sort(key=lambda e: e.get("date") or "", reverse=True)
            h2h_w = h2h_d = h2h_l = 0
            goal_diff = 0
            for m in meetings:
                if m.get("home") == found:
                    gf, ga = int(m.get("home_score") or 0), int(m.get("away_score") or 0)
                else:
                    gf, ga = int(m.get("away_score") or 0), int(m.get("home_score") or 0)
                goal_diff += gf - ga
                if gf > ga:
                    h2h_w += 1
                elif gf == ga:
                    h2h_d += 1
                else:
                    h2h_l += 1
            result["head_to_head"] = {
                "opponent": other, "meetings": len(meetings),
                "wins_draws_losses_from": f"W{h2h_w} D{h2h_d} L{h2h_l}",
                "goal_difference": goal_diff,
                "list": [{"date": m.get("date"), "league": m.get("league"),
                          "fixture": f"{m.get('home')} vs {m.get('away')}",
                          "score": f"{m.get('home_score')}-{m.get('away_score')}"} for m in meetings[:10]],
            }
    return (result)


@_tool(ReadTool)
def screen_odds(
    prices: Annotated[list[dict], Field(description="offers, each {match, market, selection, odds, probability}; probability is YOUR estimate 0-1, odds the price offered")],
    margin_pct: Annotated[float, Field(description="required edge in % before a price is flagged")] = 3.0,
    kelly_fraction: Annotated[float, Field(description="Kelly scaling, 0.25 = quarter Kelly")] = 0.25,
    tax_pct: Annotated[float, Field(description="share of stake the book passes on, e.g. 0.053 for Germany")] = 0.0,
) -> dict[str, Any]:
    """Screen a whole list of offered prices at once and return only the ones worth taking, ranked.

    One call for a full slate instead of one call per price: de-vig, fair odds, EV, minimum odds and
    a scaled Kelly stake for every offer, filtered at `margin_pct` and sorted by edge. Offers above
    MAX_PLAUSIBLE_EV are flagged separately — those pairings are almost certainly wrong lines, not value.

    Args:
        prices: offers, each {match, market, selection, odds, probability}
        margin_pct: required edge in % (default 3)
        kelly_fraction: Kelly scaling, 0.25 = quarter Kelly
        tax_pct: share of stake the book passes on (Germany: 0.053)
    """
    if not isinstance(prices, list) or not prices:
        return _error("prices needs a non-empty list of offers")
    rows, rejected, implausible = [], [], []
    for i, offer in enumerate(prices, 1):
        if not isinstance(offer, dict):
            rejected.append({"index": i, "reason": "not an object", "offer": offer}); continue
        odds, prob = offer.get("odds"), offer.get("probability")
        if not _valid_price(odds):
            rejected.append({"index": i, "reason": "odds must be a decimal price above 1.0", "offer": offer}); continue
        if not _valid_probability(prob):
            rejected.append({"index": i, "reason": "probability must be between 0 and 1 (0.55, not 55)", "offer": offer}); continue
        odds_f, prob_f = float(odds), float(prob)  # type: ignore[arg-type]  # validated by the guards above
        ev = odds_math.ev(prob_f, odds_f, tax_pct)
        mo = odds_math.minimum_odds(prob_f, margin_pct, tax_pct)
        stake = odds_math.kelly(prob_f, odds_f, kelly_fraction, tax_pct)
        row = {
            "match": offer.get("match"), "market": offer.get("market"),
            "selection": offer.get("selection"), "odds": odds_f,
            "probability": prob_f,
            "fair_odds": ev["fair_odds"],
            "ev_pct": ev["ev_pct"],
            "minimum_odds": mo["minimum_odds"],
            "kelly_pct": stake["scaled_kelly_pct"],
            "edge_over_minimum": round(odds - mo["minimum_odds"], 3),
        }
        (implausible if not ev["plausible"] else rows).append(row)
    rows.sort(key=lambda r: -r["ev_pct"])
    return ({
        "offers_in": len(prices), "rated": len(rows),
        "rejected": rejected,
        "implausible_pairings": implausible,
        "take": [r for r in rows if r["odds"] >= r["minimum_odds"]],
        "pass": [r for r in rows if r["odds"] < r["minimum_odds"]],
        "settings": {"margin_pct": margin_pct, "kelly_fraction": kelly_fraction, "tax_pct": tax_pct},
        "note": "EV is your own estimate against the price; the arithmetic never invents a probability.",
    })


def main() -> None:
    """Entry point: MCP over stdio (default) or streamable HTTP via SOCCER_MCP_HTTP.
    HTTP mode: SOCCER_MCP_HTTP=1 → serves at SOCCER_MCP_HTTP_HOST/PORT (default 127.0.0.1:8788)."""
    import os
    if os.environ.get("SOCCER_MCP_HTTP"):
        host = os.environ.get("SOCCER_MCP_HTTP_HOST", "127.0.0.1")
        port = int(os.environ.get("SOCCER_MCP_HTTP_PORT", "8788"))
        mcp.run(transport="streamable-http", host=host, port=port)
    else:
        mcp.run()  # stdio — Claude Desktop / uvx clients


if __name__ == "__main__":
    main()
