"""Odds arithmetic: de-vigging, fair odds, EV, minimum odds, Kelly, parlays.

1/o is the break-even probability a price implies and still contains the bookmaker margin. The
de-vigged probability is the market's own estimate and is what any model comparison must use —
comparing a model against raw 1/o inflates the edge by roughly the overround (4-6 % on a 1X2).
"""
from __future__ import annotations


def devig(prices: list[float]) -> dict:
    """Remove the bookmaker margin from one market's prices (proportional method)."""
    prices = [float(p) for p in prices if p and float(p) > 1.0]
    if len(prices) < 2:
        raise ValueError("need at least two prices of the same market to de-vig")
    raw = [1.0 / p for p in prices]
    total = sum(raw)
    return {
        "overround_pct": round((total - 1.0) * 100, 2),
        "fair_probabilities": [round(x / total, 4) for x in raw],
        "fair_odds": [round(total / x, 3) for x in raw],
        "fair_odds_raw": [round(1.0 / x, 3) for x in raw],
    }


def ev(probability: float, odds: float) -> dict:
    """Expected value of a unit stake at the given price."""
    probability, odds = float(probability), float(odds)
    if not 0 < probability < 1:
        raise ValueError("probability must be between 0 and 1")
    if odds <= 1.0:
        raise ValueError("odds must be greater than 1.0")
    edge = probability * odds - 1.0
    return {
        "probability": probability,
        "odds": odds,
        "fair_odds": round(1.0 / probability, 3),
        "ev_pct": round(edge * 100, 2),
        "ev_per_unit": round(edge, 4),
        "value": edge > 0,
        "minimum_odds_for_break_even": round(1.0 / probability, 3),
    }


def minimum_odds(probability: float, margin_pct: float = 3.0) -> dict:
    """Price below which a bet stops being worth taking: fair odds plus a required margin."""
    probability = float(probability)
    if not 0 < probability < 1:
        raise ValueError("probability must be between 0 and 1")
    fair = 1.0 / probability
    return {"fair_odds": round(fair, 3), "required_margin_pct": margin_pct,
            "minimum_odds": round(fair * (1.0 + margin_pct / 100.0), 3)}


def kelly(probability: float, odds: float, fraction: float = 0.25) -> dict:
    """Kelly stake, scaled: full Kelly is far too aggressive on an estimated probability."""
    probability, odds = float(probability), float(odds)
    b = odds - 1.0
    if b <= 0:
        raise ValueError("odds must be greater than 1.0")
    full = (probability * b - (1.0 - probability)) / b
    return {"full_kelly_pct": round(full * 100, 2),
            "scaled_kelly_pct": round(max(0.0, full) * fraction * 100, 2),
            "fraction": fraction}


def parlay(legs: list[dict]) -> dict:
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
        "ev_pct": round((combined_probability * combined_odds - 1.0) * 100, 2),
        "fair_combined_odds": round(1.0 / combined_probability, 3),
        "break_even_probability_pct": round(100.0 / combined_odds, 2),
        "note": "Bookmakers margin every leg, so the combined edge shrinks faster than the legs suggest.",
    }
