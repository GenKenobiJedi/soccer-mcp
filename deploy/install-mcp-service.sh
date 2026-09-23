#!/usr/bin/env bash
# Installiere soccer-mcp als systemd-Dienst (HTTP-Mode, Port 8790)
set -euo pipefail

cat > /etc/systemd/system/soccer-mcp.service <<UNIT
[Unit]
Description=Soccer MCP server (streamable HTTP, port 8790)
After=network.target

[Service]
ExecStart=/root/.hermes/hermes-agent/venv/bin/soccer-mcp
WorkingDirectory=/root/soccer-mcp
Environment=SOCCER_MCP_HTTP=1
Environment=SOCCER_MCP_HTTP_HOST=127.0.0.1
Environment=SOCCER_MCP_HTTP_PORT=8790
Environment=SOCCER_MCP_PLUGINS=soccer_mcp.plugins_sentiment
Environment=SOCCER_SENTIMENT_URL=https://vmd194739.contaboserver.net/soccer
Environment=SOCCER_SENTIMENT_TOKEN=/root/soccer/config/token-placeholder
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now soccer-mcp.service
sleep 3
systemctl is-active soccer-mcp.service
