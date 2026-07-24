#!/usr/bin/env bash
# nctl_keys.sh — pull predefined NCTL keys out of the running container.
#
# The makesoftware/casper-nctl image with PREDEFINED_ACCOUNTS=true creates a
# faucet + 5 user accounts with stable keys. This script copies the ones we
# need for integration tests into a host directory the tests can read.
#
# Usage:
#   ./scripts/nctl_keys.sh                       # default: /tmp/nctl-keys
#   ./scripts/nctl_keys.sh /path/to/dest         # explicit dest
#
# The script waits until the container is healthy before copying (fresh
# containers need ~10-20s for the assets tree to populate).

set -euo pipefail

CONTAINER="${NCTL_CONTAINER:-ae402-casper-nctl}"
DEST="${1:-/tmp/nctl-keys}"

echo "→ nctl_keys.sh: container=${CONTAINER}, dest=${DEST}"

# Wait for the container to exist and be running.
for i in $(seq 1 30); do
  if docker inspect -f '{{.State.Running}}' "${CONTAINER}" 2>/dev/null | grep -q true; then
    break
  fi
  echo "  waiting for container ${CONTAINER} to start (${i}/30)..."
  sleep 2
done
if ! docker inspect -f '{{.State.Running}}' "${CONTAINER}" 2>/dev/null | grep -q true; then
  echo "✗ container ${CONTAINER} is not running" >&2
  exit 1
fi

# Wait until the assets tree exists inside the container (~10-20s post-start).
for i in $(seq 1 60); do
  if docker exec "${CONTAINER}" test -f /home/casper/casper-node/utils/nctl/assets/net-1/faucet/secret_key.pem 2>/dev/null; then
    break
  fi
  echo "  waiting for NCTL assets tree (${i}/60)..."
  sleep 2
done

mkdir -p "${DEST}"
NCTL_ROOT="/home/casper/casper-node/utils/nctl/assets/net-1"

# faucet — used to fund user accounts and deploy the escrow contract
docker exec "${CONTAINER}" cat "${NCTL_ROOT}/faucet/secret_key.pem" > "${DEST}/faucet-secret_key.pem"
docker exec "${CONTAINER}" cat "${NCTL_ROOT}/faucet/public_key_hex" > "${DEST}/faucet-public_key_hex"

# users 1..3 — sender / receiver / arbiter
for u in 1 2 3; do
  docker exec "${CONTAINER}" cat "${NCTL_ROOT}/users/user-${u}/secret_key.pem" > "${DEST}/user-${u}-secret_key.pem"
  docker exec "${CONTAINER}" cat "${NCTL_ROOT}/users/user-${u}/public_key_hex" > "${DEST}/user-${u}-public_key_hex"
done

chmod 600 "${DEST}"/*-secret_key.pem
echo "✓ keys written to ${DEST}"
ls -la "${DEST}"
