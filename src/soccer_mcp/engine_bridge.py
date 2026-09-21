"""Optional bridge to a local analysis engine (e.g. /opt/your-engine).

Off unless SOCCER_ENGINE_PATH points at an importable engine directory. The public tools never
depend on it: they use free data (ESPN day scoreboard) and self-contained odds arithmetic only,
so the server works for anyone who clones it. The bridge is for the operator's own deployment,
where paid feeds and private keys exist.
"""
from __future__ import annotations

import importlib
import os
import sys
import pathlib

_path = os.environ.get("SOCCER_ENGINE_PATH", "")
if _path:
    sys.path.insert(0, str(pathlib.Path(_path).expanduser()))


def available() -> dict:
    if not _path:
        return {"available": False, "reason": "SOCCER_ENGINE_PATH is not set"}
    try:
        module = importlib.import_module("sources")
        return {"available": True, "path": _path, "module_file": getattr(module, "__file__", "?")}
    except Exception as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}


def sharp_reference(league: str, day: str) -> dict:
    """Free sharp-line reference for one league/day, when the engine is present."""
    info = available()
    if not info["available"]:
        return info
    import datetime
    sources = importlib.import_module("sources")
    events = sources.espn_events(league, datetime.date.fromisoformat(day))
    return {"available": True, "league": league, "day": day, "events": len(events),
            "sample": [{"home": e.get("home"), "away": e.get("away"), "score": e.get("score")} for e in events[:5]]}
