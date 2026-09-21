# Stdio MCP server: `docker run -i --rm soccer-mcp`
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SOCCER_MCP_CACHE=/cache

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . && mkdir -p /cache

# stdio transport: no port, no entrypoint shell noise on stdout
ENTRYPOINT ["soccer-mcp"]
