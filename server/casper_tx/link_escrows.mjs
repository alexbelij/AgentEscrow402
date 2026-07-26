/**
 * link_escrows.mjs — Submit escrow-manager `link_escrows` on-chain call.
 *
 * Multi-hop A2A choreography: registers that `child_service_hash` follows
 * `parent_service_hash` at position `hop_index` in an intent chain whose
 * folded attestation root is `chain_root_hash`. Append-only, zero fund
 * movement — the manager contract enforces immutability.
 *
 * Reads config from env vars:
 *   MANAGER_CONTRACT_HASH   — 64-char hex escrow-manager contract hash
 *   PARENT_SERVICE_HASH     — 64-lower-hex service_hash of the parent escrow
 *   CHILD_SERVICE_HASH      — 64-lower-hex service_hash of the child escrow
 *   CHAIN_ROOT_HASH         — 64-lower-hex chain-root (folded off-chain)
 *   HOP_INDEX               — non-negative integer (child's position in chain)
 *   PEM_PATH                — path to deployer PEM private key
 *   KEY_ALGO                — "secp256k1" (default) or "ed25519"
 *   CASPER_RPC              — RPC URL (default: testnet)
 *   CSPR_CLOUD_API_KEY      — optional cspr.cloud Authorization header
 *
 * Outputs JSON to stdout: {"hash": "...", "success": true,
 *   "parent_service_hash": "...", "child_service_hash": "...",
 *   "chain_root_hash": "...", "hop_index": N}
 * Exits non-zero on error.
 */

import fs from 'fs';
import sdk from 'casper-js-sdk';

const {
  PrivateKey,
  KeyAlgorithm,
  ContractCallBuilder,
  RpcClient,
  HttpHandler,
  Args,
  CLValue,
} = sdk;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const MANAGER_CONTRACT_HASH = process.env.MANAGER_CONTRACT_HASH;
const PARENT_SERVICE_HASH = process.env.PARENT_SERVICE_HASH;
const CHILD_SERVICE_HASH = process.env.CHILD_SERVICE_HASH;
const CHAIN_ROOT_HASH = process.env.CHAIN_ROOT_HASH;
const HOP_INDEX = process.env.HOP_INDEX;
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = process.env.KEY_ALGO || 'secp256k1';

const HEX64 = /^[0-9a-f]{64}$/;

function fail(msg) {
  process.stdout.write(JSON.stringify({ success: false, error: msg }) + '\n');
  process.exit(1);
}

function requireHex64(name, value) {
  if (!value || !HEX64.test(value)) {
    fail(`${name} missing or not 64-lower-hex`);
  }
}

async function main() {
  requireHex64('MANAGER_CONTRACT_HASH', MANAGER_CONTRACT_HASH);
  requireHex64('PARENT_SERVICE_HASH', PARENT_SERVICE_HASH);
  requireHex64('CHILD_SERVICE_HASH', CHILD_SERVICE_HASH);
  requireHex64('CHAIN_ROOT_HASH', CHAIN_ROOT_HASH);

  if (PARENT_SERVICE_HASH === CHILD_SERVICE_HASH) {
    fail('parent_service_hash == child_service_hash (a hop cannot link to itself)');
  }

  const hopIndex = Number.parseInt(HOP_INDEX ?? '', 10);
  if (!Number.isInteger(hopIndex) || hopIndex < 0) {
    fail('HOP_INDEX must be a non-negative integer');
  }

  if (!PEM_PATH) fail('PEM_PATH missing');
  if (!fs.existsSync(PEM_PATH)) fail(`PEM file not found: ${PEM_PATH}`);

  const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  const sk = PrivateKey.fromPem(fs.readFileSync(PEM_PATH, 'utf8'), algo);

  const args = Args.fromMap({
    parent_service_hash: CLValue.newCLString(PARENT_SERVICE_HASH),
    child_service_hash: CLValue.newCLString(CHILD_SERVICE_HASH),
    chain_root_hash: CLValue.newCLString(CHAIN_ROOT_HASH),
    hop_index: CLValue.newCLUint64(BigInt(hopIndex)),
  });

  // Gas: pure append-only dict write, no purse touch, no escrow record
  // mutation. ~1.5 CSPR is generous — actual on-testnet cost is well
  // under 1 CSPR. Overpay a touch; unused gas is refunded on Casper.
  const payment = 1_500_000_000;

  const tx = new ContractCallBuilder()
    .byHash(MANAGER_CONTRACT_HASH)
    .entryPoint('link_escrows')
    .runtimeArgs(args)
    .from(sk.publicKey)
    .chainName('casper-test')
    .payment(payment)
    .build();

  await tx.sign(sk);
  const handler = new HttpHandler(RPC);
  if (process.env.CSPR_CLOUD_API_KEY) {
    handler.setCustomHeaders({ Authorization: process.env.CSPR_CLOUD_API_KEY });
  }
  const client = new RpcClient(handler);
  const res = await client.putTransaction(tx);
  const hash = res.transactionHash?.toHex?.() || JSON.stringify(res.transactionHash);

  process.stdout.write(
    JSON.stringify({
      success: true,
      hash,
      parent_service_hash: PARENT_SERVICE_HASH,
      child_service_hash: CHILD_SERVICE_HASH,
      chain_root_hash: CHAIN_ROOT_HASH,
      hop_index: hopIndex,
    }) + '\n',
  );
}

main().catch((err) => fail(err?.message || String(err)));
