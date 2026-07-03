/**
 * lifecycle.mjs — Submit release / refund / dispute tx via ContractCallBuilder.
 *
 * Reads config from env vars:
 *   CONTRACT_HASH   — 64-char hex escrow contract hash
 *   ENTRY_POINT     — "release" | "refund" | "dispute"
 *   SERVICE_HASH    — 64-char hex service identifier
 *   PEM_PATH        — path to deployer PEM private key
 *   KEY_ALGO        — "secp256k1" (default) or "ed25519"
 *   CASPER_RPC      — RPC URL (default: https://node.testnet.casper.network/rpc)
 *
 * Outputs JSON to stdout:  {"hash": "...", "success": true}
 * Exits non-zero on error.
 */

import fs from 'fs';
import sdk from 'casper-js-sdk';

const { PrivateKey, KeyAlgorithm, ContractCallBuilder, RpcClient, HttpHandler, Args, CLValue } = sdk;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const CONTRACT_HASH = process.env.CONTRACT_HASH;
const ENTRY_POINT = process.env.ENTRY_POINT;
const SERVICE_HASH = process.env.SERVICE_HASH;
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = process.env.KEY_ALGO || 'secp256k1';

const VALID_ENTRY_POINTS = ['release', 'refund', 'dispute'];

function fail(msg) {
  process.stdout.write(JSON.stringify({ success: false, error: msg }) + '\n');
  process.exit(1);
}

async function main() {
  if (!CONTRACT_HASH || CONTRACT_HASH.length !== 64) fail('CONTRACT_HASH missing or invalid');
  if (!ENTRY_POINT || !VALID_ENTRY_POINTS.includes(ENTRY_POINT)) fail(`ENTRY_POINT must be one of: ${VALID_ENTRY_POINTS.join(', ')}`);
  if (!SERVICE_HASH || SERVICE_HASH.length !== 64) fail('SERVICE_HASH missing or invalid');
  if (!PEM_PATH) fail('PEM_PATH missing');
  if (!fs.existsSync(PEM_PATH)) fail(`PEM file not found: ${PEM_PATH}`);

  const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  const sk = PrivateKey.fromPem(fs.readFileSync(PEM_PATH, 'utf8'), algo);

  const tx = new ContractCallBuilder()
    .byHash(CONTRACT_HASH)
    .entryPoint(ENTRY_POINT)
    .runtimeArgs(Args.fromMap({ service_hash: CLValue.newCLString(SERVICE_HASH) }))
    .from(sk.publicKey)
    .chainName('casper-test')
    .payment(5_000_000_000) // 5 CSPR — proven sufficient
    .build();

  await tx.sign(sk);
  const client = new RpcClient(new HttpHandler(RPC));
  const res = await client.putTransaction(tx);
  const hash = res.transactionHash?.toHex?.() || JSON.stringify(res.transactionHash);

  process.stdout.write(JSON.stringify({ success: true, hash }) + '\n');
}

main().catch(err => fail(err?.message || String(err)));
