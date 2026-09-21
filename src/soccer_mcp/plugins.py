"""Load private extension modules onto the server.

The public package ships the free-data and arithmetic tools only. A private deployment (paid feeds,
sharp-line engine, model blending) attaches its own tools through this hook, so both tiers expose one
consistent server while the private code never enters this repository.

Set SOCCER_MCP_PLUGINS to a comma-separated list of dotted module paths or file paths. Every entry
must expose `register(server)`, which is called with the MCPServer instance and may add tools,
resources or prompts.

    SOCCER_MCP_PLUGINS=soccer_engine.mcp_tools,/opt/private/pro_tools.py soccer-mcp
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import pathlib

ENV_VAR = "SOCCER_MCP_PLUGINS"


def _load_one(item: str):
    path = pathlib.Path(item).expanduser()
    if path.exists():
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot import plugin file: {item}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    return importlib.import_module(item)


def load(server) -> list[str]:
    """Call register(server) on every configured plugin and return the loaded entries."""
    raw = os.environ.get(ENV_VAR, "").strip()
    if not raw:
        return []
    loaded: list[str] = []
    for item in [part.strip() for part in raw.split(",") if part.strip()]:
        module = _load_one(item)                      # import errors must stay loud
        register = getattr(module, "register", None)
        if not callable(register):
            raise RuntimeError(f"plugin '{item}' has no register(server) function")
        register(server)
        loaded.append(item)
    return loaded
