import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import pytest
from mcp.server import MCPServer

from soccer_mcp import plugins

PLUGIN_SOURCE = (
    "def register(server):\n"
    "    @server.tool()\n"
    "    def sharp_line(fixture: str) -> str:\n"
    "        return '1.87'\n"
)


def test_no_plugins_configured_is_a_no_op(monkeypatch):
    monkeypatch.delenv("SOCCER_MCP_PLUGINS", raising=False)
    assert plugins.load(MCPServer("test")) == []


def test_file_plugin_registers_a_tool(tmp_path, monkeypatch):
    plugin = tmp_path / "pro_tools.py"
    plugin.write_text(PLUGIN_SOURCE)
    monkeypatch.setenv("SOCCER_MCP_PLUGINS", str(plugin))
    server = MCPServer("test")
    assert plugins.load(server) == [str(plugin)]

    tools = asyncio.run(server.list_tools())
    assert "sharp_line" in [t.name for t in tools]


def test_dotted_module_path_is_supported(monkeypatch):
    monkeypatch.setenv("SOCCER_MCP_PLUGINS", "soccer_mcp.math")     # importable, but no register()
    with pytest.raises(RuntimeError, match="register"):
        plugins.load(MCPServer("test"))


def test_plugin_without_register_fails_loudly(tmp_path, monkeypatch):
    plugin = tmp_path / "broken.py"
    plugin.write_text("x = 1\n")
    monkeypatch.setenv("SOCCER_MCP_PLUGINS", str(plugin))
    with pytest.raises(RuntimeError, match="register"):
        plugins.load(MCPServer("test"))
