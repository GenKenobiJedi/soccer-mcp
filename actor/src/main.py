#!/usr/bin/env python3
"""Apify actor: run one soccer-mcp tool call, save the result to the dataset.

Charges one PPE event per successful tool call (requires monetization setup).
"""
import json, time, datetime as dt, sys, pathlib

# make the repo src importable: actor/ sits inside the repo, parents[1] is repo root
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / 'src'))


def main():
    from apify import Actor
    Actor.init()
    inp = Actor.get_input() or {}
    tool = inp.get("tool", "get_fixtures")
    args = inp.get("arguments") or {}

    import soccer_mcp.server as srv
    fn = getattr(srv, tool, None)
    raw = getattr(fn, "fn", fn)
    if not callable(raw):
        raise RuntimeError(f"tool {tool!r} not found or not callable")

    t0 = time.time()
    try:
        result = raw(**args) if args else raw()
        ok = True
    except Exception as e:
        result, ok = {"error": f"{type(e).__name__}: {e}"}, False

    row = {
        "tool": tool,
        "arguments": args,
        "ok": ok,
        "data": result,
        "duration_ms": int((time.time() - t0) * 1000),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    Actor.push_data([row])
    if ok:
        try:
            Actor.charge(event_name="tool-call", event_count=1)
        except Exception:
            pass  # pricing not configured yet; never fail a run on monetization
    Actor.exit()


if __name__ == "__main__":
    main()
