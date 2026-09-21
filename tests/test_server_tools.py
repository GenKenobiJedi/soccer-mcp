"""Eingabeschutz der öffentlichen Tools: klare Meldung statt Stacktrace.

Der Anlass war real: `get_fixtures("morgen")` ging als MCP-„unexpected exception" mit vollem
Python-Traceback an den Aufrufer, und ein unbekannter Markt („1" statt „1X2") blieb stumm
„unsettled" — der Aufrufer erfuhr nie, warum.
"""
import json
import unittest
from unittest import mock

from soccer_mcp import server


def payload(text: str):
    return json.loads(text)


EVENT = {"date": "2026-09-20", "kickoff": "2026-09-20T15:00Z", "home": "RB Salzburg", "away": "SK Sturm Graz",
         "home_score": 3, "away_score": 0, "league": "Austrian Bundesliga", "finished": True}


class InputGuards(unittest.TestCase):
    def test_bad_date_returns_a_message_not_a_traceback(self):
        for tool in (server.get_fixtures, server.get_results):
            got = payload(tool("morgen"))
            self.assertIn("YYYY-MM-DD", got["error"])
            self.assertEqual(got["got"], "morgen")

    def test_settle_picks_needs_a_non_empty_list(self):
        self.assertIn("non-empty", payload(server.settle_picks([]))["error"])

    def test_unsettleable_market_is_named_with_the_supported_list(self):
        got = payload(server.settle_picks([{"home": "A", "away": "B", "market": "1", "odds": 2.0,
                                            "date": "2026-09-20"}]))
        err = got["picks"][0]["error"]
        self.assertIn("unknown market '1'", err)
        self.assertIn("1X2", err)                       # die gültige Liste steht in der Meldung

    def test_missing_odds_is_reported(self):
        got = payload(server.settle_picks([{"home": "A", "away": "B", "market": "O2.5",
                                            "date": "2026-09-20"}]))
        self.assertIn("above 1.0", got["picks"][0]["error"])

    def test_devig_needs_two_valid_prices(self):
        self.assertIn("at least two", payload(server.devig_market([1.95]))["error"])
        self.assertIn("above 1.0", payload(server.devig_market([1.0, 2.0]))["error"])

    def test_evaluate_price_rejects_a_percentage_probability(self):
        self.assertIn("0 and 1", payload(server.evaluate_price(probability=55, odds=1.9))["error"])

    def test_parlay_needs_two_valid_legs(self):
        self.assertIn("at least two", payload(server.parlay_math([{"odds": 1.8, "probability": 0.6}]))["error"])
        got = payload(server.parlay_math([{"odds": 1.8, "probability": 0.6}, {"odds": 0.5, "probability": 0.5}]))
        self.assertIn("leg 2", got["error"])


class SettlementOffline(unittest.TestCase):
    """Abrechnung ohne Netz: Fixture wird gestellt, geprüft wird die Bewertung."""

    def setUp(self):
        self.patch = mock.patch.object(server.sources, "day_events", lambda day, ttl=None: [dict(EVENT)])
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_lowercase_market_is_accepted_and_graded(self):
        got = payload(server.settle_picks([
            {"home": "RB Salzburg", "away": "SK Sturm Graz", "market": "1x2", "odds": 2.0, "date": "2026-09-20"},
            {"home": "RB Salzburg", "away": "SK Sturm Graz", "market": "o2.5", "odds": 1.9, "date": "2026-09-20"},
            {"home": "RB Salzburg", "away": "SK Sturm Graz", "market": "btts", "odds": 1.8, "date": "2026-09-20"},
        ]))
        results = [(p["market"], (p.get("result"))) for p in got["picks"]]
        self.assertEqual(results, [("1X2", "win"), ("O2.5", "win"), ("BTTS", "loss")])
        self.assertEqual(got["summary"]["settled"], 3)
        self.assertEqual(got["summary"]["wins"], 2)
        self.assertEqual(got["summary"]["profit_units"], 0.9)      # +1.0 (1X2 @2.0) +0.9 (O2.5 @1.9) −1.0 (BTTS)

    def test_unmatched_pick_keeps_the_confidence(self):
        got = payload(server.settle_picks([{"home": "Erfundene Stadt", "away": "Gibt Es Nicht",
                                            "market": "1X2", "odds": 2.0, "date": "2026-09-20"}]))
        self.assertEqual(got["picks"][0]["error"], "no matching fixture found")
        self.assertIn("match_confidence", got["picks"][0])


if __name__ == "__main__":
    unittest.main()
