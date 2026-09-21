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
