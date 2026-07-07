/**
 * batch_lifecycle.mjs — Submit escrow-manager batch_release / batch_cancel.
 *
 * Calls `batch_release` or `batch_cancel` on the escrow-manager contract
 * (NOT the main escrow contract — the manager has its own escrow dict for
 * batch-created escrows).
 *
 * Reads config from env vars:
 *   MANAGER_CONTRACT_HASH  — 64-char hex escrow-manager contract hash
 *   ENTRY_POINT            — "batch_release" | "batch_cancel"
 *   SERVICE_HASHES_JSON    — JSON array of 64-char hex service hashes to process
 *   PEM_PATH               — path to deployer PEM private key
 *   KEY_ALGO               — "secp256k1" (default) or "ed25519"
 *   CASPER_RPC             — RPC URL (default: testnet)
 *
 * Outputs JSON to stdout:  {"hash": "...", "success": true, "count": N}
 * Exits non-zero on error.
 */

import fs from 'fs';
import sdk from 'casper-js-sdk';

const { PrivateKey, KeyAlgorithm, ContractCallBuilder, RpcClient, HttpHandler, Args, CLValue, CLTypeString } = sdk;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const MANAGER_CONTRACT_HASH = process.env.MANAGER_CONTRACT_HASH;
const ENTRY_POINT = process.env.ENTRY_POINT;
const SERVICE_HASHES = JSON.parse(process.env.SERVICE_HASHES_JSON || '[]');
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = process.env.KEY_ALGO || 'secp256k1';

const VALID_ENTRY_POINTS = ['batch_release', 'batch_cancel'];

function fail(msg) {
  process.stdout.write(JSON.stringify({ success: false, error: msg }) + '\n');
  process.exit(1);
}

async function main() {
  if (!MANAGER_CONTRACT_HASH || MANAGER_CONTRACT_HASH.length !== 64) fail('MANAGER_CONTRACT_HASH missing or invalid');
  if (!ENTRY_POINT || !VALID_ENTRY_POINTS.includes(ENTRY_POINT)) fail(`ENTRY_POINT must be one of: ${VALID_ENTRY_POINTS.join(', ')}`);
  if (SERVICE_HASHES.length === 0) fail('SERVICE_HASHES_JSON empty');
  if (SERVICE_HASHES.length > 50) fail('batch size exceeds contract MAX_BATCH_SIZE (50)');
  if (!PEM_PATH) fail('PEM_PATH missing');
  if (!fs.existsSync(PEM_PATH)) fail(`PEM file not found: ${PEM_PATH}`);

  const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  const sk = PrivateKey.fromPem(fs.readFileSync(PEM_PATH, 'utf8'), algo);

  const args = Args.fromMap({
    service_hashes: CLValue.newCLList(CLTypeString, SERVICE_HASHES.map((s) => CLValue.newCLString(s))),
  });

  // Gas: ~2 CSPR base + ~0.5 CSPR per escrow in batch (release has fee
  // deduction + two purse-to-purse transfers per escrow; cancel has one).
  const n = SERVICE_HASHES.length;
  const payment = 2_000_000_000 + n * 1_000_000_000;

  const tx = new ContractCallBuilder()
    .byHash(MANAGER_CONTRACT_HASH)
    .entryPoint(ENTRY_POINT)
    .runtimeArgs(args)
    .from(sk.publicKey)
    .chainName('casper-test')
    .payment(payment)
    .build();

  await tx.sign(sk);
  const _handler = new HttpHandler(RPC);
  if (process.env.CSPR_CLOUD_API_KEY) {
    _handler.setCustomHeaders({ Authorization: process.env.CSPR_CLOUD_API_KEY });
  }
  const client = new RpcClient(_handler);
  const res = await client.putTransaction(tx);
  const hash = res.transactionHash?.toHex?.() || JSON.stringify(res.transactionHash);

  process.stdout.write(JSON.stringify({ success: true, hash, count: n }) + '\n');
}

main().catch((err) => fail(err?.message || String(err)));
