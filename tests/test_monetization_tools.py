"""Tests für die beiden Verkaufs-Tools: get_team_form und screen_odds.

Beide sind der Grund, warum der Actor mehr als €0 einnehmen soll, also gehören sie
unter Test: falsche Eingaben müssen eine Meldung liefern, nicht stillschweigend
Müll, und der Screen darf niemals eine Fantasie-Wahrscheinlichkeit erfinden.
"""
import json
import unittest
from unittest import mock

from soccer_mcp import server


def payload(result):
    return json.loads(result) if isinstance(result, str) else result


def finished(day, home, away, hs, ag, league="Testliga"):
    return {"date": day, "kickoff": f"{day}T15:00Z", "home": home, "away": away,
            "home_score": hs, "away_score": ag, "league": league, "finished": True}


class FakeCalendar:
    """Minimaler day_events-Ersatz: feste Tage statt Netz."""

    def __init__(self, days: dict):
        self.days = days

    def day_events(self, day: str):
        return list(self.days.get(day, []))


class TeamForm(unittest.TestCase):
    def _patch(self, days):
        return mock.patch.object(server.sources, "day_events", FakeCalendar(days).day_events)

    def test_record_and_form_string_come_from_real_scores(self):
        import datetime
        today = datetime.date.today()
        d0 = today.isoformat()
        d1 = (today - datetime.timedelta(days=2)).isoformat()
        d2 = (today - datetime.timedelta(days=4)).isoformat()
        days = {
            d0: [finished(d0, "Bayern Munich", "Werder Bremen", 3, 1)],
            d1: [finished(d1, "RB Leipzig", "Bayern Munich", 1, 1)],
            d2: [finished(d2, "Bayern Munich", "Augsburg", 2, 0)],
        }
        with self._patch(days):
            got = payload(server.get_team_form(team="Bayern Munich", lookback_days=7))
        self.assertEqual(got["team"], "Bayern Munich")
        self.assertEqual(got["record"], {"W": 2, "D": 1, "L": 0})
        self.assertEqual(got["goals_for"], 6)
        self.assertEqual(got["goals_against"], 2)
        self.assertEqual(got["form_string"], "WDW")
        self.assertEqual(got["win_rate_pct"], 66.7)
        self.assertEqual(got["matches"], 3)

    def test_team_name_is_matched_fuzzily(self):
        import datetime
        d0 = datetime.date.today().isoformat()
        days = {d0: [finished(d0, "Bayern Munich", "Werder Bremen", 1, 0)]}
        with self._patch(days):
            got = payload(server.get_team_form(team="Bayern", lookback_days=7))
        self.assertEqual(got["team"], "Bayern Munich")

    def test_empty_team_is_refused(self):
        got = payload(server.get_team_form(team="  "))
        self.assertIn("non-empty", got["error"])

    def test_unknown_team_reports_known_names(self):
        import datetime
        d0 = datetime.date.today().isoformat()
        days = {d0: [finished(d0, "Alpha FC", "Beta United", 1, 0)]}
        with self._patch(days):
            got = payload(server.get_team_form(team="Fussball Klub Nirgendwo", lookback_days=7))
        self.assertIn("no team close to", got["error"])
        self.assertIn("known_sample", got)

    def test_h2h_never_resolves_onto_the_first_team(self):
        """Regression: h2h_against traf fuzzy auf denselben Verein und meldete 0 Spiele,
        statt den falschen Namen zu nennen. Zweiter Club muss zweiter Club bleiben."""
        import datetime
        d0 = datetime.date.today().isoformat()
        d1 = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
        days = {
            d0: [finished(d0, "Alpha FC", "Beta United", 2, 0)],
            d1: [finished(d1, "Alpha FC", "Beta United", 3, 1)],
        }
        with self._patch(days):
            got = payload(server.get_team_form(team="Alpha FC", lookback_days=7, h2h_against="Beta United"))
        h2h = got["head_to_head"]
        self.assertEqual(h2h["opponent"], "Beta United")
        self.assertEqual(h2h["meetings"], 2)
        self.assertEqual(h2h["wins_draws_losses_from"], "W2 D0 L0")
        self.assertEqual(h2h["goal_difference"], 4)

    def test_h2h_against_the_same_team_is_an_error_not_zero_meetings(self):
        import datetime
        d0 = datetime.date.today().isoformat()
        days = {d0: [finished(d0, "Alpha FC", "Beta United", 2, 0)]}
        with self._patch(days):
            got = payload(server.get_team_form(team="Alpha FC", lookback_days=7, h2h_against="Alpha FC"))
        self.assertIn("error", got["head_to_head"])
        self.assertIn("no second team", got["head_to_head"]["error"])


class ScreenOdds(unittest.TestCase):
    def test_empty_list_is_refused(self):
        self.assertIn("non-empty", payload(server.screen_odds([]))["error"])

    def test_take_and_pass_are_separated_at_the_margin(self):
        got = payload(server.screen_odds(
            prices=[
                {"match": "A vs B", "selection": "A", "odds": 1.72, "probability": 0.62},
                {"match": "C vs D", "selection": "Over", "odds": 2.05, "probability": 0.55},
            ], margin_pct=3.0, tax_pct=0.053))
        self.assertEqual(got["offers_in"], 2)
        self.assertEqual(got["rated"], 2)
        # 1.72 < minimum (1.75 mit Tax) -> pass; 2.05 > 1.98 -> take
        self.assertEqual([r["match"] for r in got["take"]], ["C vs D"])
        self.assertEqual([r["match"] for r in got["pass"]], ["A vs B"])
        # 5.3 % Steuer drückt den Mindestpreis nach oben
        self.assertGreater(got["take"][0]["minimum_odds"], got["take"][0]["fair_odds"])

    def test_invalid_offer_is_rejected_not_silently_dropped(self):
        got = payload(server.screen_odds(prices=[
            {"match": "A", "odds": 1.0, "probability": 0.5},
            {"match": "B", "odds": 2.0, "probability": 55},
            {"match": "C", "odds": 2.0, "probability": 0.5},
        ]))
        self.assertEqual(got["rated"], 1)
        self.assertEqual(len(got["rejected"]), 2)
        self.assertIn("decimal price", got["rejected"][0]["reason"])
        self.assertIn("between 0 and 1", got["rejected"][1]["reason"])

    def test_absurd_pairing_is_flagged_separately_from_value(self):
        """Der bekannte Multi-Line-Fall: faire 0.985 auf Quote 30 ist keine 2698-%-Kante,
        sondern eine falsche Zuordnung. Solche Zeilen dürfen nie in `take` landen."""
        got = payload(server.screen_odds(prices=[
            {"match": "X", "selection": "away +5", "odds": 30.0, "probability": 0.985},
        ]))
        self.assertEqual(got["take"], [])
        self.assertEqual(len(got["implausible_pairings"]), 1)
        self.assertGreater(got["implausible_pairings"][0]["ev_pct"], 1000)

    def test_rows_are_ranked_by_edge(self):
        # 1.90 @ 0.52 needs 1.961 minimum -> pass; 3.00 @ 0.45 needs 2.229 -> take.
        got = payload(server.screen_odds(prices=[
            {"match": "small", "odds": 1.90, "probability": 0.52},
            {"match": "big", "odds": 3.00, "probability": 0.45},
        ]))
        self.assertEqual([r["match"] for r in got["take"]], ["big"])
        self.assertEqual([r["match"] for r in got["pass"]], ["small"])
        # Reihenfolge im take-Block ist nach Kante, nicht nach Eingabe
        many = payload(server.screen_odds(prices=[
            {"match": "a", "odds": 2.20, "probability": 0.48},
            {"match": "b", "odds": 3.00, "probability": 0.45},
            {"match": "c", "odds": 2.60, "probability": 0.42},
        ]))
        self.assertEqual([r["match"] for r in many["take"]], ["b", "c", "a"])

    def test_settings_are_echoed(self):
        got = payload(server.screen_odds(prices=[{"match": "A", "odds": 2.0, "probability": 0.5}],
                                         margin_pct=5.0, kelly_fraction=0.5, tax_pct=0.05))
        self.assertEqual(got["settings"], {"margin_pct": 5.0, "kelly_fraction": 0.5, "tax_pct": 0.05})


class ReserveDetection(unittest.TestCase):
    """Regression: the marker list was substring-based, so "Totting-ham" matched "am" and
    "Amsterdam" matched "am" — both senior sides were classified as youth teams, which then
    made "Spurs" and "Ajax" unresolvable."""

    CASES = [
        ("Tottenham Hotspur", False), ("Tottenham Hotspur U21", True),
        ("Real Madrid", False), ("Real Madrid Castilla", True),
        ("Ajax Amsterdam", False), ("AFC Ajax Amateurs", True),
        ("Internazionale", False), ("Internazionale Primavera", True),
        ("Barcelona", False), ("Barcelona B", True), ("Chelsea U21", True),
        ("Fenerbahce", False), ("Manchester United", False), ("AC Milan", False),
    ]

    def test_senior_and_youth_sides_are_told_apart(self):
        for name, expected in self.CASES:
            with self.subTest(name=name):
                self.assertEqual(server._is_youth_or_reserve(name), expected)


class NicknameResolution(unittest.TestCase):
    """A nickname must resolve to the senior side, never to a reserve team, and a genuinely
    ambiguous input must ask rather than guess."""

    def _names(self, extra):
        import datetime
        d0 = datetime.date.today().isoformat()
        days = {d0: [finished(d0, a, b, 1, 0) for a, b in extra]}
        return days

    def _form(self, teams, **kw):
        with mock.patch.object(server.sources, "day_events", FakeCalendar(self._names(teams)).day_events):
            return payload(server.get_team_form(team=kw.pop("team"), lookback_days=7, **kw))

    def test_nickname_resolves_to_senior_side(self):
        for query, expected in [("Man United", "Manchester United"), ("Man Utd", "Manchester United"),
                                ("BVB", "Borussia Dortmund"), ("Juve", "Juventus"),
                                ("Spurs", "Tottenham Hotspur"), ("Ajax", "Ajax Amsterdam"),
                                ("Wolves", "Wolverhampton Wanderers"), ("Real", "Real Madrid")]:
            with self.subTest(query=query):
                got = self._form([(expected, "Away FC"), (expected + " U21", "Away FC"),
                                  (expected + " B", "Away FC")], team=query)
                self.assertEqual(got.get("team"), expected)

    def test_ambiguous_prefix_asks_instead_of_guessing(self):
        # No alias for "Sporting", and both candidates are senior sides: must ask, not pick one.
        got = self._form([("Sporting CP", "Away"), ("Sporting Gijon", "Away")], team="Sporting")
        self.assertIn("error", got)
        self.assertIn("ambiguous", got)
        self.assertIn("Sporting CP", got["did_you_mean"])

    def test_prefix_prefers_the_senior_side_over_a_reserve(self):
        """"Porto" is Porto FC and Porto Alegre SC; the latter carries the reserve token "sc",
        so the senior side is the only sensible reading and must not be reported as ambiguous."""
        got = self._form([("Porto FC", "Away"), ("Porto Alegre SC", "Away")], team="Porto")
        self.assertEqual(got.get("team"), "Porto FC")

    def test_alias_wins_over_a_shared_prefix(self):
        """"Real" is an explicit alias for Real Madrid, so it resolves even though Real Sociedad
        is also in the window. An alias is a stronger statement than a string coincidence."""
        got = self._form([("Real Sociedad", "Away"), ("Real Madrid", "Away")], team="Real")
        self.assertEqual(got.get("team"), "Real Madrid")

    def test_unknown_name_still_reports_known_sample(self):
        got = self._form([("Alpha FC", "Beta United")], team="Fussball Klub Nirgendwo")
        self.assertIn("no team close to", got["error"])
        self.assertIn("known_sample", got)


if __name__ == "__main__":
    unittest.main()
