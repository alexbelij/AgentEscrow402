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
 *   ARBITER_PUBKEYS_JSON     — (reveal_swap only, optional) JSON array of hex-encoded
 *                              arbiter public keys. Required only when the escrow
 *                              amount exceeds the A1 release_cap (see main.rs
 *                              require_arbiter_cap_approval); omit/"[]" under cap.
 *   ARBITER_SIGNATURES_JSON  — (reveal_swap only, optional) matching JSON array of
 *                              hex-encoded signatures over "reveal_swap:{SERVICE_HASH}".
 *   PEM_PATH        — path to signer PEM private key
 *   KEY_ALGO        — "secp256k1" (default) or "ed25519"
 *   CASPER_RPC      — RPC URL (default: https://node.testnet.casper.network/rpc)
 *
 * Outputs JSON to stdout: {"hash": "...", "success": true}
 */

import fs from 'fs';
import sdk from 'casper-js-sdk';

const { PrivateKey, KeyAlgorithm, ContractCallBuilder, RpcClient, HttpHandler, Args, CLValue } = sdk;
const CLTypeString = sdk.default ? sdk.default.CLTypeString : sdk.CLTypeString;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const CONTRACT_HASH = process.env.CONTRACT_HASH;
const ENTRY_POINT = process.env.ENTRY_POINT;
const SERVICE_HASH = process.env.SERVICE_HASH;
const COMMIT_HASH = process.env.COMMIT_HASH;
const PREIMAGE = process.env.PREIMAGE;
const ARBITER_PUBKEYS_JSON = process.env.ARBITER_PUBKEYS_JSON;
const ARBITER_SIGNATURES_JSON = process.env.ARBITER_SIGNATURES_JSON;
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = process.env.KEY_ALGO || 'secp256k1';

function fail(msg) {
  process.stdout.write(JSON.stringify({ success: false, error: msg }) + '\n');
  process.exit(1);
}

function parseArbiterArrays() {
  let pubkeys = [];
  let sigs = [];
  if (ARBITER_PUBKEYS_JSON) {
    try {
      pubkeys = JSON.parse(ARBITER_PUBKEYS_JSON);
      if (!Array.isArray(pubkeys)) throw new Error('not an array');
    } catch {
      fail('ARBITER_PUBKEYS_JSON must be a JSON array of hex-encoded arbiter public keys');
    }
  }
  if (ARBITER_SIGNATURES_JSON) {
    try {
      sigs = JSON.parse(ARBITER_SIGNATURES_JSON);
      if (!Array.isArray(sigs)) throw new Error('not an array');
    } catch {
      fail('ARBITER_SIGNATURES_JSON must be a JSON array of hex-encoded signatures');
    }
  }
  if (pubkeys.length !== sigs.length) fail('ARBITER_PUBKEYS_JSON and ARBITER_SIGNATURES_JSON must have equal length');
  return { pubkeys, sigs };
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
    const { pubkeys, sigs } = parseArbiterArrays();
    argsMap.arbiter_pubkeys = CLValue.newCLList(CLTypeString, pubkeys.map(a => CLValue.newCLString(a)));
    argsMap.arbiter_signatures = CLValue.newCLList(CLTypeString, sigs.map(a => CLValue.newCLString(a)));
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
  const _handler = new HttpHandler(RPC);
if (process.env.CSPR_CLOUD_API_KEY) {
  _handler.setCustomHeaders({ Authorization: process.env.CSPR_CLOUD_API_KEY });
}
const client = new RpcClient(_handler);
  const res = await client.putTransaction(tx);
  const hash = res.transactionHash?.toHex?.() || JSON.stringify(res.transactionHash);

  process.stdout.write(JSON.stringify({ success: true, hash }) + '\n');
}

main().catch((e) => fail(e.message || String(e)));
