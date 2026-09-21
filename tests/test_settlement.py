import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from soccer_mcp import settlement


def test_whole_line_can_push():
    assert settlement.outcome("O2.0AH", 2, 0, 1.30)["result"] == "void"
    assert settlement.outcome("O2.0AH", 2, 1, 1.30)["result"] == "win"
    assert settlement.outcome("O2.0AH", 1, 0, 1.30)["result"] == "loss"


def test_quarter_line_splits_the_stake():
    half = settlement.outcome("O2.25AH", 1, 1, 1.50)
    assert half["result"] == "halfloss" and half["profit"] == -0.5
    # three goals: O2.0 wins and O2.5 wins → full win, not a half win
    win = settlement.outcome("O2.25AH", 2, 1, 1.50)
    assert win["result"] == "win" and win["profit"] == 0.5
    # 2.75 with three goals: O2.5 wins, O3.0 pushes → half a win
    half = settlement.outcome("O2.75AH", 2, 1, 1.60)
    assert half["result"] == "halfwin" and half["profit"] == 0.3


def test_half_line_is_binary():
    assert settlement.outcome("O2.5", 1, 1, 1.40)["result"] == "loss"
    assert settlement.outcome("O2.5", 2, 1, 1.40)["result"] == "win"


def test_under_and_btts_and_1x2():
    assert settlement.outcome("U2.5", 1, 1, 1.90)["result"] == "win"
    assert settlement.outcome("BTTS", 1, 1, 1.80)["result"] == "win"
    assert settlement.outcome("BTTS", 2, 0, 1.80)["result"] == "loss"
    assert settlement.outcome("1X2", 2, 0, 1.60)["result"] == "win"
    assert settlement.outcome("1X2", 0, 0, 1.60)["result"] == "loss"


def test_missing_inputs_return_none():
    assert settlement.outcome("O2.5", None, 1, 1.5) is None
    assert settlement.outcome(None, 1, 1, 1.5) is None
    assert settlement.outcome("O2.5", 1, 1, None) is None
