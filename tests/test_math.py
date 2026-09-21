import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import pytest
from soccer_mcp import math as odds_math


def test_devig_is_proportional_and_removes_the_margin():
    result = odds_math.devig([1.75, 3.6, 4.4])
    assert result["overround_pct"] > 0
    assert pytest.approx(sum(result["fair_probabilities"]), abs=1e-3) == 1.0   # rounded output
    # De-vigging removes the margin, so the implied probability drops below 1/o and the fair
    # odds move above the offered price — the bookmaker's cut is exactly that gap.
    assert result["fair_probabilities"][0] < 1 / 1.75
    assert result["fair_odds"][0] > 1.75
    assert pytest.approx(result["fair_odds"][0] * result["fair_probabilities"][0], abs=1e-2) == 1.0


def test_ev_flags_value_and_break_even_price():
    good = odds_math.ev(0.55, 1.95)
    assert good["value"] is True and good["ev_pct"] > 0
    bad = odds_math.ev(0.55, 1.70)
    assert bad["value"] is False and bad["ev_pct"] < 0
    assert pytest.approx(good["minimum_odds_for_break_even"], abs=0.002) == 1 / 0.55


def test_minimum_odds_adds_the_required_margin():
    result = odds_math.minimum_odds(0.5, 5.0)
    assert pytest.approx(result["fair_odds"], abs=0.001) == 2.0
    assert pytest.approx(result["minimum_odds"], abs=0.001) == 2.1


def test_kelly_scales_and_never_returns_a_negative_stake():
    result = odds_math.kelly(0.55, 2.0, 0.25)
    assert 0 < result["scaled_kelly_pct"] < result["full_kelly_pct"]
    assert odds_math.kelly(0.30, 2.0)["scaled_kelly_pct"] == 0.0


def test_parlay_multiplies_and_shows_the_decay():
    result = odds_math.parlay([{"probability": 0.6, "odds": 1.8}, {"probability": 0.5, "odds": 2.0}])
    assert pytest.approx(result["combined_odds"], abs=0.001) == 3.6
    assert pytest.approx(result["combined_probability"], abs=0.0001) == 0.3


def test_devig_needs_at_least_two_prices():
    with pytest.raises(ValueError):
        odds_math.devig([1.5])


def test_devig_defaults_to_the_power_method():
    """Wie in der Engine: proportional verteilt die Marge gleichmäßig und überschätzt Außenseiter."""
    power = odds_math.devig([1.80, 3.50, 4.20])
    prop = odds_math.devig([1.80, 3.50, 4.20], method="proportional")
    assert power["method"] == "power"
    assert power["fair_probabilities"][2] < prop["fair_probabilities"][2]
    assert power["fair_probabilities"][0] > prop["fair_probabilities"][0]
    assert pytest.approx(sum(power["fair_probabilities"]), abs=0.001) == 1.0
    assert power["overround_pct"] == prop["overround_pct"]


def test_devig_rejects_an_unknown_method():
    with pytest.raises(ValueError):
        odds_math.devig([1.8, 3.5], method="magic")


def test_ev_applies_a_passed_on_tax():
    net = odds_math.ev(0.40, 3.20, tax_pct=0.053)
    assert pytest.approx(net["ev_per_unit"], abs=0.0001) == 0.40 * 3.20 * (1 - 0.053) - 1
    assert net["tax_pct"] == 0.053
    assert odds_math.ev(0.40, 3.20)["ev_per_unit"] > net["ev_per_unit"]


def test_kelly_uses_net_odds_when_tax_is_passed_on():
    gross = odds_math.kelly(0.55, 2.10)["scaled_kelly_pct"]
    net = odds_math.kelly(0.55, 2.10, tax_pct=0.053)["scaled_kelly_pct"]
    assert gross > net > 0
    # Bei Quote 1.90 frisst die Steuer die Kante ganz: 0.55 * 1.90 * 0.947 < 1 → Kelly 0.
    assert odds_math.kelly(0.55, 1.90, tax_pct=0.053)["scaled_kelly_pct"] == 0.0


def test_absurd_edge_is_flagged_not_sold():
    """An EV beyond +100 % is a mapping error, not an edge.

    Measured 2026-09-21: a fair 0.985 for "away +3" met the price 26.0 of another line — arithmetically
    +2461 %. Multi-line handicaps and team totals map by opaque outcome ids, so this happens quietly.
    """
    got = odds_math.ev(0.985, 26.0)
    assert got["value"] is True            # arithmetically still positive
    assert got["plausible"] is False       # but not believable
    assert "another line" in got["note"]


def test_normal_edge_is_plausible():
    got = odds_math.ev(0.45, 2.40)
    assert got["ev_pct"] > 0
    assert got["plausible"] is True
    assert got["note"] is None
