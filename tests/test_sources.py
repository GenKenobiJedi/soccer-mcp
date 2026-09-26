"""Offline fixture-cache regressions; no live cache, keys, or upstream calls."""
import datetime
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from soccer_mcp import leagues, sources


TODAY = "2026-09-26"
PAST = "2026-09-25"
NOW = datetime.datetime(2026, 9, 26, 12, tzinfo=datetime.timezone.utc).timestamp()


def event(**changes):
    row = {
        "date": PAST,
        "kickoff": f"{PAST}T18:00Z",
        "home": "Test Home",
        "away": "Test Away",
        "home_score": 0,
        "away_score": 0,
        "league": "Test League",
        "league_id": "1",
        "finished": False,
        "status": "60'",
    }
    return {**row, **changes}


def scoreboard(*, completed=True, home_score="2", away_score="1"):
    return {"events": [{
        "uid": "s:600~l:1~e:123",
        "date": f"{PAST}T18:00Z",
        "competitions": [{
            "status": {"type": {"completed": completed, "detail": "Full Time" if completed else "60'"}},
            "competitors": [
                {"homeAway": "home", "team": {"displayName": "Test Home"}, "score": home_score},
                {"homeAway": "away", "team": {"displayName": "Test Away"}, "score": away_score},
            ],
        }],
    }]}


@pytest.fixture(autouse=True)
def isolated_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(sources, "TTL", 900)
    monkeypatch.setattr(sources, "FINISHED_DAY_TTL", 604800)
    monkeypatch.setattr(sources, "time", SimpleNamespace(time=lambda: NOW, strftime=lambda fmt: TODAY))
    monkeypatch.setattr(leagues, "league_map", lambda: {"1": {"name": "Test League"}})
    network = Mock(side_effect=AssertionError("Network is forbidden in cache tests"))
    monkeypatch.setattr(sources.urllib.request, "urlopen", network)
    fetch = Mock(return_value=scoreboard())
    monkeypatch.setattr(sources, "_fetch", fetch)
    yield fetch
    network.assert_not_called()


@pytest.fixture
def seed_cache():
    def seed(events, *, day=PAST, age=0):
        path = sources.CACHE_DIR / f"day-{day}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(events), encoding="utf-8")
        os.utime(path, (NOW - age, NOW - age))
        return path
    return seed


@pytest.mark.parametrize("status", ["60'", "Scheduled", "Postponed", "Canceled", ""])
def test_past_unfinished_events_refresh_after_short_ttl(seed_cache, isolated_sources, status):
    seed_cache([event(status=status)], age=sources.TTL)

    rows = sources.day_events(PAST)

    isolated_sources.assert_called_once_with(PAST)
    assert rows[0]["finished"] is True
    assert rows[0]["home_score"] == 2


def test_mixed_past_day_refreshes_after_short_ttl(seed_cache, isolated_sources):
    seed_cache([event(finished=True, status="Full Time"), event()], age=sources.TTL)

    sources.day_events(PAST)

    isolated_sources.assert_called_once_with(PAST)


def test_empty_past_day_refreshes_after_short_ttl(seed_cache, isolated_sources):
    seed_cache([], age=sources.TTL)

    rows = sources.day_events(PAST)

    isolated_sources.assert_called_once_with(PAST)
    assert len(rows) == 1


def test_finished_without_scores_is_not_a_verified_finished_day(seed_cache, isolated_sources):
    seed_cache([event(finished=True, home_score=None)], age=sources.TTL)

    sources.day_events(PAST)

    isolated_sources.assert_called_once_with(PAST)


def test_verified_finished_past_day_keeps_long_ttl(seed_cache, isolated_sources):
    seed_cache([event(finished=True, status="Full Time")], age=sources.FINISHED_DAY_TTL - 1)

    rows = sources.day_events(PAST)

    isolated_sources.assert_not_called()
    assert rows[0]["finished"] is True
    assert rows[0]["home_score"] == 0


def test_finished_past_day_refreshes_at_long_ttl(seed_cache, isolated_sources):
    seed_cache([event(finished=True, status="Full Time")], age=sources.FINISHED_DAY_TTL)

    sources.day_events(PAST)

    isolated_sources.assert_called_once_with(PAST)


def test_recent_unfinished_cache_stays_usable(seed_cache, isolated_sources):
    seed_cache([event()], age=sources.TTL - 1)

    rows = sources.day_events(PAST)

    isolated_sources.assert_not_called()
    assert rows[0]["finished"] is False
    assert rows[0]["home_score"] == 0


@pytest.mark.parametrize("day", [TODAY, "2026-09-27"])
def test_nonpast_finished_days_use_short_ttl(seed_cache, isolated_sources, day):
    seed_cache([event(finished=True, date=day)], day=day, age=sources.TTL)

    sources.day_events(day)

    isolated_sources.assert_called_once_with(day)


@pytest.mark.parametrize("age", [0, -60, 1])
def test_zero_ttl_always_forces_fetch(seed_cache, isolated_sources, age):
    seed_cache([event(finished=True)], age=age)

    sources.day_events(PAST, ttl=0)

    isolated_sources.assert_called_once_with(PAST)


@pytest.mark.parametrize("finished,age,ttl", [(True, 10, 10), (False, 1000, 1001)])
def test_explicit_ttl_overrides_default(seed_cache, isolated_sources, finished, age, ttl):
    seed_cache([event(finished=finished)], age=age)

    sources.day_events(PAST, ttl=ttl)

    assert isolated_sources.call_count == (1 if age >= ttl else 0)


def iso_time(timestamp):
    return datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc).isoformat()


def test_cold_fetch_has_provenance_in_a_list_cache(isolated_sources):
    rows = sources.day_events(PAST)

    assert isinstance(rows, list)
    assert rows[0]["source"] == "ESPN"
    assert rows[0]["provenance"] == {
        "fetched_at": iso_time(NOW),
        "fetched_at_basis": "upstream",
        "cache_status": "miss",
        "stale": False,
        "fetch_error": None,
    }
    cached = json.loads((sources.CACHE_DIR / f"day-{PAST}.json").read_text())
    assert isinstance(cached, list)
    assert cached == rows
    isolated_sources.assert_called_once_with(PAST)


def test_legacy_cache_hit_discloses_mtime_as_fetch_time(seed_cache, isolated_sources):
    path = seed_cache([event()], age=45)
    before = path.read_bytes(), path.stat().st_mtime_ns

    rows = sources.day_events(PAST)

    assert rows[0]["source"] == "ESPN"
    assert rows[0]["provenance"] == {
        "fetched_at": iso_time(NOW - 45),
        "fetched_at_basis": "cache_mtime",
        "cache_status": "hit",
        "stale": False,
        "fetch_error": None,
    }
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    isolated_sources.assert_not_called()


def test_cache_hit_preserves_recorded_fetch_timestamp(seed_cache, isolated_sources):
    metadata = {
        "fetched_at": iso_time(NOW - 3600), "fetched_at_basis": "upstream",
        "cache_status": "refresh", "stale": False, "fetch_error": None,
    }
    seed_cache([event(finished=True, source="ESPN", provenance=metadata)], age=30)

    rows = sources.day_events(PAST)

    assert rows[0]["provenance"] == {**metadata, "cache_status": "hit"}
    isolated_sources.assert_not_called()


def test_successful_refresh_clears_stale_metadata_without_inventing_scores(seed_cache, isolated_sources):
    seed_cache([event(provenance={
        "fetched_at": iso_time(NOW - 1000), "fetched_at_basis": "upstream",
        "cache_status": "stale", "stale": True, "fetch_error": "TimeoutError: old failure",
    })], age=sources.TTL)
    isolated_sources.return_value = scoreboard(completed=False, home_score=None, away_score=None)

    row = sources.day_events(PAST)[0]

    assert row["finished"] is False
    assert row["home_score"] is None and row["away_score"] is None
    assert row["provenance"] == {
        "fetched_at": iso_time(NOW), "fetched_at_basis": "upstream",
        "cache_status": "refresh", "stale": False, "fetch_error": None,
    }


@pytest.mark.parametrize("finished", [False, True])
def test_failed_refresh_discloses_staleness_without_rewriting_cache(seed_cache, isolated_sources, finished):
    old = event(finished=finished, home_score=None if not finished else 0)
    age = sources.FINISHED_DAY_TTL
    path = seed_cache([old], age=age)
    before = path.read_bytes(), path.stat().st_mtime_ns
    isolated_sources.side_effect = TimeoutError("timed out")

    for _ in range(2):
        row = sources.day_events(PAST)[0]
        assert {key: row[key] for key in old} == old
        assert row["source"] == "ESPN"
        assert row["provenance"] == {
            "fetched_at": iso_time(NOW - age), "fetched_at_basis": "cache_mtime",
            "cache_status": "stale", "stale": True, "fetch_error": "TimeoutError: timed out",
        }
    assert isolated_sources.call_count == 2
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_failed_forced_refresh_preserves_original_fetch_time(seed_cache, isolated_sources):
    fetched_at = iso_time(NOW - 10)
    seed_cache([event(provenance={"fetched_at": fetched_at, "fetched_at_basis": "upstream"})])
    isolated_sources.side_effect = TimeoutError("timed out")

    provenance = sources.day_events(PAST, ttl=0)[0]["provenance"]

    assert provenance["fetched_at"] == fetched_at
    assert provenance["cache_status"] == "stale"
    assert provenance["stale"] is True
    assert provenance["fetch_error"] == "TimeoutError: timed out"


@pytest.mark.parametrize("cached", [None, []])
def test_failure_without_events_to_annotate_is_not_silent(seed_cache, isolated_sources, cached):
    if cached is not None:
        seed_cache(cached, age=sources.TTL)
    isolated_sources.side_effect = TimeoutError("timed out")

    with pytest.raises(RuntimeError, match="ESPN scoreboard fetch failed.*timed out"):
        sources.day_events(PAST)


@pytest.mark.parametrize("contents", [b"{", b"", b"{}", b"null", b"[null]", b"[{}]",
                                      b'[{"finished": "false"}]', b'"\xff"'])
def test_corrupt_cache_refetches(seed_cache, isolated_sources, contents):
    path = seed_cache([event()])
    path.write_bytes(contents)
    os.utime(path, (NOW, NOW))

    rows = sources.day_events(PAST)

    isolated_sources.assert_called_once_with(PAST)
    assert rows[0]["home_score"] == 2
    assert rows[0]["provenance"]["cache_status"] == "miss"
    assert json.loads(path.read_text()) == rows


def test_corrupt_cache_is_not_a_fallback_on_fetch_failure(seed_cache, isolated_sources):
    path = seed_cache([event()])
    path.write_text("{", encoding="utf-8")
    isolated_sources.side_effect = TimeoutError("timed out")

    with pytest.raises(RuntimeError, match="ESPN scoreboard fetch failed.*timed out"):
        sources.day_events(PAST)
    isolated_sources.assert_called_once_with(PAST)


def test_parse_failure_uses_disclosed_stale_fallback(seed_cache, monkeypatch):
    seed_cache([event()], age=sources.TTL)
    monkeypatch.setattr(sources, "_parse", Mock(side_effect=ValueError("invalid scoreboard")))

    row = sources.day_events(PAST)[0]

    assert row["finished"] is False
    assert row["provenance"]["stale"] is True
    assert row["provenance"]["fetch_error"] == "ValueError: invalid scoreboard"
