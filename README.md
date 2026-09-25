# soccer-mcp

An MCP server that gives AI agents **football fixtures, real results, bet settlement and honest odds
arithmetic** — one day, every competition, no API key.

**Live on Apify:** [soccer-fixtures-odds-math](https://apify.com/genkenobi/soccer-fixtures-odds-math) (pay-per-call) ·
**On Smithery:** [soccer-mcp](https://smithery.ai/servers/soccer/soccer-mcp) ·
**Preview video (25 s):** [soccer-mcp in 25 seconds — real MCP calls](https://youtu.be/OZN5YrTOXTw) ·
**Videos & demos on YouTube:** [TorAlarm](https://www.youtube.com/@TorAlarm)

Most football MCP servers wrap a paid data API and stop at "here is a list of matches". This one
ships the part that is usually missing: turning a price into a verdict. It de-vigs a market, compares
your probability against the offered odds, names the minimum price worth taking, sizes the stake and
settles the result against the real scoreline — including push and quarter-line handling that most
quick scripts get wrong.

## Tools

| Tool | What it answers |
|---|---|
| `get_fixtures(date, league?, only_finished?)` | Every football match on a day, all competitions, with scores once played |
| `get_results(date, league?)` | Finished matches with final score — the input for settling |
| `settle_picks(picks, date?)` | Settle a list of picks against real scorelines: per-pick result, hit rate, PnL, ROI |
| `devig_market(prices, method?)` | Strip the bookmaker margin and return the market's own probabilities (power method by default) |
| `evaluate_price(probability, odds, margin_pct?, kelly_fraction?, tax_pct?)` | Fair odds, EV, minimum odds, scaled Kelly stake, take-it verdict |
| `parlay_math(legs)` | Combined odds/EV of an accumulator and how fast the edge decays per leg |
| `get_team_sentiment(date?, teams?)` | **Team-Mood cards**: news sentiment per club — net score −1…+1, level (🔴/🟡/🟢), trend, hard absences, factor list with sources and sentiment deltas. Sentiment scores are model-assisted (LLM per-factor deltas) and weighted for freshness + source quality (unverified ×0.35); they are mood indicators, not betting advice. |
| `engine_status()` | Whether the optional private engine bridge is wired up |

## Arithmetic conventions

* **`ev()` reports `plausible`.** An edge above `MAX_PLAUSIBLE_EV` (+100 %) is arithmetically fine but
  almost certainly a broken price-to-line pairing: multi-line Asian handicaps and team totals map by
  opaque outcome ids, and a fair 98.5 % for "away +3" once met the price 26.0 of another line (+2461 %).
  Check the pairing before acting on such a number — never present it as value.
* **A fair value that equals your own model value is your model, not the market.** When the sharp line
  does not quote a market (BTTS, over/under, team totals) and the number is filled from a goal model
  fitted to 1X2, the two converge by construction. Treat it as model-based, and do not let a goal model
  lead on BTTS or over/under, where it is measurably over-confident.

* **De-vigging uses the power method** (`p_i = (1/o_i)^k`, `Σp_i = 1`), not a proportional split of
  the overround. Proportional de-vigging spreads the margin evenly and therefore overstates outsiders:
  on `[1.80, 3.50, 4.20]` the two methods differ by **1.5 percentage points** on the 4.20 — more than
  half of a typical 2 % value threshold. `devig_market(prices, method="proportional")` still returns
  the old numbers for comparison.
* **Bookmaker tax is a parameter, not an assumption**: `tax_pct` (Germany: 5.3 % at books that pass it
  on) comes off the payout, so it lowers `ev`, raises `minimum_odds` and shrinks the Kelly stake. All
  three arithmetic tools take it; default 0.
* **Settlement names** are historic: `1X2` means the **home win**, `2X2` the away win and `DC` home or
  draw. `X` (draw), `X2` (away or draw) and `12` (no draw) are also accepted, and so are the short
  codes another engine writes (`1`, `2`, `1X`, `12`, …) — they map onto the same markets, so a pick
  written elsewhere still settles instead of silently falling through.

## Install

```bash
pip install soccer-mcp          # or: uvx soccer-mcp
```

Run it as a stdio MCP server:

```bash
soccer-mcp
```

## Use with a client

Claude Desktop / Cursor / any MCP client (`mcp.json`):

```json
{
  "mcpServers": {
    "soccer": {
      "command": "uvx",
      "args": ["soccer-mcp"],
      "env": { "SOCCER_MCP_CACHE": "/tmp/soccer-mcp-cache" }
    }
  }
}
```

With Docker:

```json
{
  "mcpServers": {
    "soccer": { "command": "docker", "args": ["run", "-i", "--rm", "soccer-mcp"] }
  }
}
```

## Private tools (premium tier)

The public package stays keyless and free. A private deployment attaches its own tools — paid feeds,
sharp lines, model blending — through a plugin hook, so one server exposes both tiers:

```bash
SOCCER_MCP_PLUGINS=soccer_engine.mcp_tools,/opt/private/pro_tools.py soccer-mcp
```

Each plugin is a module (dotted path or file path) with a `register(server)` function that adds tools to
the same server. Nothing private enters this repository, and `engine_status()` reports what is loaded.
`SOCCER_ENGINE_PATH` optionally points at a private engine directory to bridge into.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `SOCCER_MCP_CACHE` | `~/.cache/soccer-mcp` | Where day scoreboards are cached |
| `SOCCER_MCP_TTL` | `900` | Cache seconds for the current day |
| `SOCCER_MCP_FINISHED_TTL` | `604800` | Cache seconds for past days (scores never change) |
| `SOCCER_ENGINE_PATH` | unset | Operator-only: path to a private analysis engine to bridge into |
| `SOCCER_MCP_PLUGINS` | unset | Comma-separated plugin modules (e.g. `soccer_mcp.plugins_sentiment`) |
| `SOCCER_SENTIMENT_URL` | unset | Team-Mood backend base URL (e.g. `https://…/soccer`) — enables `get_team_sentiment` |
| `SOCCER_SENTIMENT_TOKEN` | unset | Bearer token for the Team-Mood backend. On Apify: set this as a **secret** environment variable in the Console (Actor → Settings → Environment variables), not in the repo |

## Example

```
evaluate_price(probability=0.55, odds=1.95, margin_pct=3)
→ fair_odds 1.818, ev_pct +7.25, minimum_odds 1.873, take_it true, stake.scaled_kelly_pct 3.75

settle_picks(picks=[{"home": "VfB Stuttgart", "away": "Borussia Dortmund",
                     "market": "O2.5", "odds": 1.29, "date": "2026-09-18"}])
→ score "0:1", result "loss", profit -1.0, roi_pct -100.0
```

## Data source and limits

Fixtures and results come from ESPN's public day scoreboard (all competitions, one request per day,
cached). Requests carry **no custom User-Agent** — ESPN answers 403 to every custom UA. Date ranges
are rejected by that endpoint, so the server fetches by day.

Competition names are not part of the "all competitions" payload — each event only carries an ESPN
league id. The server therefore builds an `id -> name` map once (74 leagues, roughly 45 s, cached for
30 days via `SOCCER_MCP_LEAGUE_TTL`) and enriches each match with it. Competitions outside that map
keep an empty name, so every match also carries `league_id` and can still be grouped. The `league`
argument of `get_fixtures`/`get_results` is a case-insensitive substring filter: `"Bundesliga"`
matches the German **and** the Austrian one — pass `league_id` when you need certainty.

Know what this is not: the fixtures feed has no odds, no lineups and no xG. `get_fixtures` and
`get_results` are free public data; **the arithmetic tools take your own probability as input and
never invent one**. Nothing here promises profit: every model estimate is yours, and a positive
expected value on a handful of picks is noise.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q                                   # odds arithmetic and settlement logic
python tests/smoke_stdio.py                 # end-to-end: real tool calls over stdio
docker build -t soccer-mcp . && \
  printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"c","version":"1"}}}\n' | docker run -i --rm soccer-mcp
```

Works on both MCP SDK generations: the server imports `MCPServer` (v2) and falls back to `FastMCP`
(v1), and every tool returns JSON text, which both versions hand to the client unchanged.

## License

MIT — see [LICENSE](LICENSE).

## Distribution

| Channel | Link |
|---|---|
| Smithery registry | [smithery.ai/servers/burhan-hayber/soccer-mcp](https://smithery.ai/servers/burhan-hayber/soccer-mcp) |
| MCP gateway URL | `https://mcp.smithery.ai/burhan-hayber/soccer-mcp` (Bearer Smithery key) |
| Self-host (public, key-free) | `https://vmd194739.contaboserver.net/mcp/soccer/mcp` |
| Apify (PPE, pay-per-call) | https://apify.com/genkenobi/soccer-fixtures-odds-math |

Install via Smithery clients: `npx -y @smithery/cli@latest install burhan-hayber/soccer-mcp --client claude`

