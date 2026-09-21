"""Odds arithmetic: de-vigging, fair odds, EV, minimum odds, Kelly, parlays.

1/o is the break-even probability a price implies and still contains the bookmaker margin. The
de-vigged probability is the market's own estimate and is what any model comparison must use —
comparing a model against raw 1/o inflates the edge by roughly the overround (4-6 % on a 1X2).
"""
from __future__ import annotations


def power_exponent(prices: list[float]) -> float:
    """Solve p_i = (1/o_i)**k with sum(p_i) = 1 — the exponent of the power method.

    Proportional de-vigging (dividing by the overround) spreads the margin evenly and therefore
    *understates* favourites and *overstates* longshots. The power method pushes more of the margin
    onto the longshots, which is where bookmakers load it — same reason the engine uses it.
    """
    raw = [1.0 / float(p) for p in prices]
    if not raw:
        return 1.0
    lo, hi = 0.5, 3.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if sum(x ** mid for x in raw) > 1.0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def devig(prices: list[float], method: str = "power") -> dict:
    """Remove the bookmaker margin from one market's prices.

    Default is the **power method** (see `power_exponent`), which matches the engine's arithmetic.
    `method="proportional"` gives the older, simpler split-by-overround numbers for comparison.
    """
    prices = [float(p) for p in prices if p and float(p) > 1.0]
    if len(prices) < 2:
        raise ValueError("need at least two prices of the same market to de-vig")
    raw = [1.0 / p for p in prices]
    total = sum(raw)
    if method == "proportional":
        fair = [x / total for x in raw]
    elif method == "power":
        k = power_exponent(prices)
        fair = [x ** k for x in raw]
        total = sum(fair)
        fair = [x / total for x in fair]
    else:
        raise ValueError("method must be 'power' or 'proportional'")
    return {
        "method": method,
        "overround_pct": round((sum(raw) - 1.0) * 100, 2),
        "fair_probabilities": [round(x, 4) for x in fair],
        "fair_odds": [round(1.0 / x, 3) for x in fair],
        "fair_odds_raw": [round(1.0 / x, 3) for x in raw],
    }


# An EV above this is not an opportunity but a broken price-to-line pairing: with a multi-line Asian
# handicap or team-total feed the outcome ids are opaque, and a fair 0.985 for "away +3" met the price
# 26.0 of another line — arithmetically +2461 %. Report it, never sell it as value.
MAX_PLAUSIBLE_EV = 1.0


def ev(probability: float, odds: float, tax_pct: float = 0.0) -> dict:
    """Expected value of a unit stake at the given price.

    `tax_pct` is the share of the stake the bookmaker passes on (Germany: 5.3 % at books that do
    not absorb it). It applies to the stake, so it scales the payout: p·o·(1−tax) − 1.

    `plausible` is False when the edge exceeds `MAX_PLAUSIBLE_EV`: the arithmetic still holds, but the
    inputs almost certainly do not describe the same line. Check the pairing before acting on it.
    """
    probability, odds = float(probability), float(odds)
    if not 0 < probability < 1:
        raise ValueError("probability must be between 0 and 1")
    if odds <= 1.0:
        raise ValueError("odds must be greater than 1.0")
    net_odds = odds * (1.0 - float(tax_pct))
    edge = probability * net_odds - 1.0
    plausible = edge <= MAX_PLAUSIBLE_EV
    return {
        "probability": probability,
        "odds": odds,
        "tax_pct": float(tax_pct),
        "fair_odds": round(1.0 / probability, 3),
        "ev_pct": round(edge * 100, 2),
        "ev_per_unit": round(edge, 4),
        "value": edge > 0,
        "plausible": plausible,
        "note": (None if plausible else
                 f"EV above {MAX_PLAUSIBLE_EV:.0%} — the price almost certainly belongs to another "
                 "line (multi-line handicaps and team totals map by opaque outcome ids). Check the "
                 "pairing before acting on it."),
        "minimum_odds_for_break_even": round(1.0 / (probability * (1.0 - float(tax_pct))), 3),
    }


def minimum_odds(probability: float, margin_pct: float = 3.0, tax_pct: float = 0.0) -> dict:
    """Price below which a bet stops being worth taking: fair odds plus a required margin.

    With a passed-on tax the required price is higher, because the tax comes off the payout:
    1 / (p·(1−tax)) is the price at which the bet merely breaks even.
    """
    probability = float(probability)
    if not 0 < probability < 1:
        raise ValueError("probability must be between 0 and 1")
    fair = 1.0 / probability
    break_even = 1.0 / (probability * (1.0 - float(tax_pct)))
    return {"fair_odds": round(fair, 3), "required_margin_pct": margin_pct,
            "tax_pct": float(tax_pct), "break_even_odds": round(break_even, 3),
            "minimum_odds": round(break_even * (1.0 + margin_pct / 100.0), 3)}


def kelly(probability: float, odds: float, fraction: float = 0.25, tax_pct: float = 0.0) -> dict:
    """Kelly stake, scaled: full Kelly is far too aggressive on an estimated probability."""
    probability, odds = float(probability), float(odds)
    b = odds * (1.0 - float(tax_pct)) - 1.0
    if b <= 0:
        raise ValueError("odds must be greater than 1.0")
    full = (probability * b - (1.0 - probability)) / b
    return {"full_kelly_pct": round(full * 100, 2),
            "scaled_kelly_pct": round(max(0.0, full) * fraction * 100, 2),
            "fraction": fraction}


def parlay(legs: list[dict], tax_pct: float = 0.0) -> dict:
    """Combined odds and EV of an accumulator; legs are {'probability', 'odds'}."""
    if not legs:
        raise ValueError("need at least one leg")
    combined_odds, combined_probability = 1.0, 1.0
    for leg in legs:
        combined_odds *= float(leg["odds"])
        combined_probability *= float(leg["probability"])
    return {
        "legs": len(legs),
        "combined_odds": round(combined_odds, 3),
        "combined_probability": round(combined_probability, 4),
        "tax_pct": float(tax_pct),
        "ev_pct": round((combined_probability * combined_odds * (1.0 - float(tax_pct)) - 1.0) * 100, 2),
        "fair_combined_odds": round(1.0 / combined_probability, 3),
        "break_even_probability_pct": round(100.0 / combined_odds, 2),
        "note": "Bookmakers margin every leg, so the combined edge shrinks faster than the legs suggest.",
    }
