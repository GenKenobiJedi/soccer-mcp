"""ESPN league ids -> names.

The "all competitions" day scoreboard carries no league name: each event only holds a uid like
`s:600~l:720~e:401914260`, where the middle part is the ESPN league id. League *names* come from the
per-league scoreboard, so this module collects them once (curated slug list, ~60 calls) and caches the
id -> {name, slug} map. Unknown ids stay empty in the output, but the raw id is always returned so a
caller can still group by competition.
"""
from __future__ import annotations

import json
import os
import pathlib
import time
import urllib.request

from .sources import CACHE_DIR

BASE = "https://site.web.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
MAP_FILE = "leagues.json"
MAP_TTL = int(os.environ.get("SOCCER_MCP_LEAGUE_TTL", str(30 * 86400)))

# Curated on purpose: one request per slug, only while the map is being built. Extend freely.
SLUGS = [
    "eng.1", "eng.2", "eng.3", "eng.4", "eng.5", "sco.1", "sco.2", "irl.1", "wal.1", "nir.1",
    "ger.1", "ger.2", "ger.3", "esp.1", "esp.2", "esp.3", "ita.1", "ita.2", "ita.3",
    "fra.1", "fra.2", "fra.3", "ned.1", "ned.2", "por.1", "por.2", "bel.1", "bel.2",
    "tur.1", "tur.2", "gre.1", "pol.1", "rou.1", "den.1", "den.2", "nor.1", "nor.2",
    "swe.1", "swe.2", "fin.1", "aut.1", "aut.2", "sui.1", "sui.2", "cze.1", "cro.1",
    "srb.1", "hun.1", "bul.1", "svk.1", "slo.1", "ukr.1", "rus.1", "isr.1", "cyp.1", "isl.1",
    "usa.1", "usa.2", "usa.usl.1", "mex.1", "bra.1", "bra.2", "arg.1", "uru.1", "chi.1",
    "col.1", "per.1", "ecu.1", "par.1", "bol.1", "ven.1", "crc.1", "hon.1", "gua.1", "slv.1",
    "jpn.1", "jpn.2", "kor.1", "chn.1", "ksa.1", "uae.1", "qat.1", "irn.1", "ind.1",
    "rsa.1", "egy.1", "mar.1", "tun.1", "nga.1", "ken.1", "gha.1", "alg.1", "aus.1", "nzl.1",
    "uefa.champions", "uefa.europa", "uefa.europa_conf", "concacaf.champions",
    "conmebol.libertadores", "conmebol.sudamericana", "fifa.world", "fifa.cwc",
]


def _map_path() -> pathlib.Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / MAP_FILE


def league_map(rebuild: bool = False) -> dict:
    """{league_id: {'name', 'slug'}} — built once, then cached."""
    path = _map_path()
    if path.exists() and not rebuild and time.time() - path.stat().st_mtime < MAP_TTL:
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            pass
    mapping = {}
    for slug in SLUGS:
        try:
            req = urllib.request.Request(BASE.format(slug=slug), headers={"Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=20) as response:      # no custom UA, see sources
                data = json.loads(response.read().decode("utf-8"))
            entry = (data.get("leagues") or [{}])[0]
            if entry.get("id"):
                mapping[str(entry["id"])] = {"name": entry.get("name") or slug,
                                             "slug": entry.get("slug") or slug}
        except Exception:
            continue                                       # a single failing slug must not break the map
    if mapping:
        path.write_text(json.dumps(mapping, ensure_ascii=False))
    return mapping
