FROM python:3.11-slim

# Install Node.js 22 for Casper tx scripts (casper-js-sdk)
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    npm install -g npm@12

WORKDIR /app

# Python deps (upgrade pip first to silence 24.0→26.x notice + get latest resolver)
RUN pip install --no-cache-dir --upgrade pip
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Node.js deps for Casper tx scripts
# --no-fund/--no-audit silence promotional noise; --omit=dev keeps image small
COPY server/casper_tx/package.json server/casper_tx/
RUN cd server/casper_tx && npm install --omit=dev --no-fund --no-audit

# App source
COPY server/ server/
COPY sdk/ sdk/
# docs/mcp_tools_schema.json is read at runtime by
# server/mcp_playground_api.py (console MCP Playground catalogue) — without
# this the deployed API silently falls back to an empty tool list.
COPY docs/ docs/

ENV PORT=10000
EXPOSE 10000
CMD ["sh", "-c", "uvicorn server.app:app --host 0.0.0.0 --port ${PORT:-10000}"]
