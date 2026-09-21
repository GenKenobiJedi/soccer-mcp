"""Settlement of football bets against real scorelines.

Quarter lines (2.25, 2.75) split the stake across the two neighbouring lines, so exactly two goals
on an Over-2.25 line returns half a stake. Whole lines can push (void). This module is deliberately
free of any betting-shop logic: it only turns a market + odds + final score into a result and PnL.
"""
from __future__ import annotations

MARKETS = {
    "O1.0AH", "O1.5", "O2.0AH", "O2.25AH", "O2.5", "O2.75AH", "O3.0AH", "O3.5",
    "U1.5", "U2.0AH", "U2.25AH", "U2.5", "U2.75AH", "BTTS", "1X2", "2X2", "DC",
    "X", "X2", "12",
}

# Die Namen oben sind gewachsen und teils irreführend: "1X2" ist der **Heimsieg**, "2X2" der
# Auswärtssieg, "DC" Heim oder Unentschieden. Wer aus der Engine kommt, schreibt "1", "2", "1X" —
# dieselben Märkte, andere Codes. Ohne diese Abbildung wird ein Tipp des einen Servers vom anderen
# stillschweigend nicht abgerechnet.
ALIASES = {"1": "1X2", "2": "2X2", "1X": "DC", "X2": "X2", "12": "12", "X": "X", "HOME": "1X2",
           "AWAY": "2X2", "DRAW": "X"}


def _ou(total: int, line: float, over: bool, win: float) -> tuple[str, float]:
    if line % 1 == 0:                                # whole line → push possible
        if total == line:
            return "void", 0.0
        ok = total > line if over else total < line
        return ("win" if ok else "loss", win if ok else -1.0)
    if round(line * 4) % 2 == 1:                     # quarter line → split stake
        gain = 0.0
        for part in (line - 0.25, line + 0.25):
            if total == part:
                continue
            ok = total > part if over else total < part
            gain += (win if ok else -1.0) / 2
        gain = round(gain, 3)
        if gain >= win:
            return "win", gain
        if gain <= -1:
            return "loss", gain
        if gain == 0:
            return "void", 0.0
        return ("halfwin", gain) if gain > 0 else ("halfloss", gain)
    ok = total > line if over else total < line
    return ("win" if ok else "loss", win if ok else -1.0)


def outcome(market: str | None, home_score, away_score, odds: float | None) -> dict | None:
    """{'result', 'profit', 'line'} for one unit staked, or None when inputs are missing."""
    if not market or home_score is None or away_score is None or odds is None:
        return None
    market = ALIASES.get(market.upper().replace(" ", ""), market.upper().replace(" ", ""))
    try:
        hs, as_ = int(home_score), int(away_score)
    except (TypeError, ValueError):
        return None
    total, win = hs + as_, float(odds) - 1.0
    if market.startswith("O") and market not in ("1X2", "2X2"):
        line = float(market[1:].replace("AH", ""))
        result, profit = _ou(total, line, True, win)
    elif market.startswith("U"):
        line = float(market[1:].replace("AH", ""))
        result, profit = _ou(total, line, False, win)
    elif market == "BTTS":
        result, profit = ("win", win) if hs > 0 and as_ > 0 else ("loss", -1.0)
    elif market == "1X2":
        result, profit = ("win", win) if hs > as_ else ("loss", -1.0)
    elif market == "2X2":
        result, profit = ("win", win) if as_ > hs else ("loss", -1.0)
    elif market == "DC":
        result, profit = ("win", win) if hs >= as_ else ("loss", -1.0)
    elif market == "X":
        result, profit = ("win", win) if hs == as_ else ("loss", -1.0)
    elif market == "X2":
        result, profit = ("win", win) if as_ >= hs else ("loss", -1.0)
    elif market == "12":
        result, profit = ("win", win) if hs != as_ else ("loss", -1.0)
    else:
        return None
    return {"result": result, "profit": round(profit, 3), "total_goals": total}
