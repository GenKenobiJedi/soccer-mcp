#!/usr/bin/env python3
"""Apify actor: run one soccer-mcp tool call, save the result to the dataset.

Charges one PPE event per successful tool call (requires monetization setup).
"""
import json, time, datetime as dt, sys, pathlib

# Container: /app/main.py, package src installed as site-package `soccer_mcp`
# Do not rely on repo layout inside the image — soccer-mcp package itself is pip-installed.
if pathlib.Path("/app/src").exists():
    sys.path.insert(0, "/app/src")


def main():
    import asyncio
    from apify import Actor

    async def run():
        await Actor.init()
        inp = await Actor.get_input() or {}
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
        await Actor.push_data([row])
        if ok:
            try:
                await Actor.charge(event_name="tool-call", event_count=1)
            except Exception:
                pass  # pricing not configured yet; never fail a run on monetization
        await Actor.exit()

    asyncio.run(run())


if __name__ == "__main__":
    main()
