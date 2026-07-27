FROM python:3.11-slim-bookworm

# Install Node.js for Casper tx scripts (casper-js-sdk).
# NodeSource's deb.nodesource.com/setup_X.x bootstrap script now returns
# HTTP 403 (NodeSource deprecated it) so the previous curl-based install
# broke every fresh/cache-cold build. Install nodejs+npm straight from the
# Debian bookworm repo instead -- older (18.x) but fully sufficient for the
# casper-js-sdk-only scripts here, and has no external-URL dependency.
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

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
