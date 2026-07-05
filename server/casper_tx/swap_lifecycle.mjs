/**
 * swap_lifecycle.mjs — Submit commit_swap / reveal_swap tx (on-chain HTLC
 * atomic swap) via ContractCallBuilder.
 *
 * Env vars:
 *   CONTRACT_HASH   — 64-char hex escrow contract hash
 *   ENTRY_POINT     — "commit_swap" | "reveal_swap"
 *   SERVICE_HASH    — 64-char hex service identifier
 *   COMMIT_HASH     — (commit_swap only) hex-encoded sha256(preimage)
 *   PREIMAGE        — (reveal_swap only) the secret string
 *   PEM_PATH        — path to signer PEM private key
 *   KEY_ALGO        — "secp256k1" (default) or "ed25519"
 *   CASPER_RPC      — RPC URL (default: https://node.testnet.casper.network/rpc)
 *
 * Outputs JSON to stdout: {"hash": "...", "success": true}
 */

import fs from 'fs';
import sdk from 'casper-js-sdk';

const { PrivateKey, KeyAlgorithm, ContractCallBuilder, RpcClient, HttpHandler, Args, CLValue } = sdk;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const CONTRACT_HASH = process.env.CONTRACT_HASH;
const ENTRY_POINT = process.env.ENTRY_POINT;
const SERVICE_HASH = process.env.SERVICE_HASH;
const COMMIT_HASH = process.env.COMMIT_HASH;
const PREIMAGE = process.env.PREIMAGE;
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = process.env.KEY_ALGO || 'secp256k1';

function fail(msg) {
  process.stdout.write(JSON.stringify({ success: false, error: msg }) + '\n');
  process.exit(1);
}

async function main() {
  if (!CONTRACT_HASH || CONTRACT_HASH.length !== 64) fail('CONTRACT_HASH missing or invalid');
  if (!['commit_swap', 'reveal_swap'].includes(ENTRY_POINT)) fail('ENTRY_POINT must be commit_swap or reveal_swap');
  if (!SERVICE_HASH || SERVICE_HASH.length !== 64) fail('SERVICE_HASH missing or invalid');
  if (!PEM_PATH) fail('PEM_PATH missing');
  if (!fs.existsSync(PEM_PATH)) fail(`PEM file not found: ${PEM_PATH}`);

  const argsMap = { service_hash: CLValue.newCLString(SERVICE_HASH) };
  if (ENTRY_POINT === 'commit_swap') {
    if (!COMMIT_HASH) fail('COMMIT_HASH required for commit_swap');
    argsMap.commit_hash = CLValue.newCLString(COMMIT_HASH);
  } else {
    if (PREIMAGE === undefined) fail('PREIMAGE required for reveal_swap');
    argsMap.preimage = CLValue.newCLString(PREIMAGE);
  }

  const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  const sk = PrivateKey.fromPem(fs.readFileSync(PEM_PATH, 'utf8'), algo);

  const tx = new ContractCallBuilder()
    .byHash(CONTRACT_HASH)
    .entryPoint(ENTRY_POINT)
    .runtimeArgs(Args.fromMap(argsMap))
    .from(sk.publicKey)
    .chainName('casper-test')
    .payment(5_000_000_000) // 5 CSPR
    .build();

  await tx.sign(sk);
  const client = new RpcClient(new HttpHandler(RPC));
  const res = await client.putTransaction(tx);
  const hash = res.transactionHash?.toHex?.() || JSON.stringify(res.transactionHash);

  process.stdout.write(JSON.stringify({ success: true, hash }) + '\n');
}

main().catch((e) => fail(e.message || String(e)));
