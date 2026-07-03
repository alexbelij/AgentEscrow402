FROM python:3.11-slim

# Install Node.js 22 for Casper tx scripts (casper-js-sdk)
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Node.js deps for Casper tx scripts
COPY server/casper_tx/package.json server/casper_tx/
RUN cd server/casper_tx && npm install --omit=dev

# App source
COPY server/ server/
COPY sdk/ sdk/

ENV PORT=10000
EXPOSE 10000
CMD ["sh", "-c", "uvicorn server.app:app --host 0.0.0.0 --port ${PORT:-10000}"]
