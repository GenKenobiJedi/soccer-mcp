"""End-to-end smoke test: drive the stdio server with the official MCP client."""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> int:
    # Die Umgebung durchreichen statt sie zu ersetzen: sonst erreicht ein Aufruf wie
    # SOCCER_MCP_PLUGINS=… niemals den Server, und der Plugin-Hook lässt sich hier nicht prüfen
    # (genau daran scheiterte der erste E2E-Lauf: 7 statt 10 Tools, ohne Fehlermeldung).
    env = {**os.environ, "SOCCER_MCP_CACHE": os.environ.get("SOCCER_MCP_CACHE", "/tmp/soccer-mcp-cache")}
    params = StdioServerParameters(command=sys.executable, args=["-m", "soccer_mcp.server"], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            info = getattr(init, "server_info", None) or init.serverInfo      # v2 snake_case, v1 camelCase
            protocol = getattr(init, "protocol_version", None) or init.protocolVersion
            print("initialize:", info.name, info.version, "| Protokoll", protocol)

            tools = await session.list_tools()
            print("tools:", len(tools.tools), [t.name for t in tools.tools])

            def payload(result):
                """mcp v2 + structured output: the object lives in structuredContent; a list-returning
                tool wraps it as {"result": [...]} and streams one text block per item. Prefer the
                structured copy, fall back to the text block (older protocol versions)."""
                sc = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
                if sc is not None:
                    return sc["result"] if isinstance(sc, dict) and list(sc) == ["result"] else sc
                if len(result.content) > 1:
                    return [json.loads(block.text) for block in result.content]
                return json.loads(result.content[0].text)

            res = await session.call_tool("get_results", {"date": "2026-09-20", "league": "Bundesliga"})
            games = payload(res)
            print(f"get_results 2026-09-20 Bundesliga: {len(games)} Spiele")
            for g in games[:4]:
                print(f'    {g["home"]} {g["home_score"]}:{g["away_score"]} {g["away"]}')

            res = await session.call_tool("settle_picks", {"picks": [
                {"home": "VfB Stuttgart", "away": "Borussia Dortmund", "market": "O2.5",
                 "odds": 1.29, "date": "2026-09-18"},
                {"home": "VfB Stuttgart", "away": "Borussia Dortmund", "market": "U2.5",
                 "odds": 3.10, "date": "2026-09-18"},
                {"home": "Erfundene Stadt", "away": "Gibt Es Nicht", "market": "O1.5",
                 "odds": 1.50, "date": "2026-09-18"}]})
            data = payload(res)
            print("settle_picks:", json.dumps(data["summary"], ensure_ascii=False))
            for p in data["picks"]:
                print(f'    {p.get("fixture", p.get("home"))} {p.get("score", "")} {p["market"]} @ {p["odds"]}'
                      f' -> {p.get("result") or p.get("error")} {p.get("profit", "")}')

            res = await session.call_tool("evaluate_price", {"probability": 0.55, "odds": 1.95, "margin_pct": 3})
            price = payload(res)
            print("evaluate_price:", {"fair_odds": price["fair_odds"], "ev_pct": price["ev_pct"],
                                      "minimum_odds": price["minimum_odds"]["minimum_odds"],
                                      "take_it": price["take_it"], "kelly_pct": price["stake"]["scaled_kelly_pct"]})

            res = await session.call_tool("devig_market", {"prices": [1.75, 3.6, 4.4]})
            dev = payload(res)
            print("devig_market:", {"overround_pct": dev["overround_pct"],
                                    "fair_probabilities": dev["fair_probabilities"]})
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
