#!/usr/bin/env python3
"""Apify actor: run one soccer-mcp tool call, save the result to the dataset.

Charges one PPE event per successful tool call (requires monetization setup).
"""
import json, os, time, datetime as dt, sys, pathlib

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
        # Sentiment-Backend-Token: env (Secret in der Console) oder KV-Store 'SENTIMENT-TOKEN'
        if not os.environ.get("SOCCER_SENTIMENT_TOKEN"):
            try:
                tok = await Actor.get_value("SENTIMENT-TOKEN")
                if tok:
                    os.environ["SOCCER_SENTIMENT_TOKEN"] = str(tok)
            except Exception:
                pass  # Backend antwortet dann 401 — tool liefert ok:false, Run bleibt grün
        fn = getattr(srv, tool, None)
        raw = getattr(fn, "fn", fn)
        if not callable(raw):
            raise RuntimeError(f"tool {tool!r} not found or not callable")

        t0 = time.perf_counter()
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
            "duration_ms": int((time.perf_counter() - t0) * 1000),
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        await Actor.push_data([row])
        # Run-Info in den KeyValue-Store (OUTPUT record) — Pflicht laut output_schema.json
        try:
            await Actor.set_value(
                "OUTPUT",
                {
                    "tool": tool,
                    "arguments": args,
                    "ok": ok,
                    "duration_ms": row["duration_ms"],
                    "generated_at": row["generated_at"],
                },
            )
        except Exception:
            pass
        if ok:
            try:
                await Actor.charge(event_name="tool-call", event_count=1)
            except Exception:
                pass  # pricing not configured yet; never fail a run on monetization
        await Actor.exit()

    asyncio.run(run())


if __name__ == "__main__":
    main()
