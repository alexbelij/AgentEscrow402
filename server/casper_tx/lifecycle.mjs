/**
 * lifecycle.mjs — Submit release / refund / dispute tx via ContractCallBuilder.
 *
 * Reads config from env vars:
 *   CONTRACT_HASH             — 64-char hex escrow contract hash
 *   ENTRY_POINT               — "release" | "refund" | "dispute"
 *   SERVICE_HASH              — 64-char hex service identifier
 *   ARBITER_PUBKEYS_JSON      — (release only, optional) JSON array of hex-encoded
 *                               arbiter public keys. Required (non-empty, and
 *                               >= on-chain arbiter_threshold) only when the escrow
 *                               amount exceeds the contract's A1 release_cap;
 *                               omit or pass "[]" for under-cap releases.
 *   ARBITER_SIGNATURES_JSON   — (release only, optional) matching JSON array of
 *                               hex-encoded signatures over
 *                               "release:{SERVICE_HASH}" (see
 *                               server/arbiter_crypto.py build_cap_approval_message).
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
const CLTypeString = sdk.default ? sdk.default.CLTypeString : sdk.CLTypeString;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const CONTRACT_HASH = process.env.CONTRACT_HASH;
const ENTRY_POINT = process.env.ENTRY_POINT;
const SERVICE_HASH = process.env.SERVICE_HASH;
const ARBITER_PUBKEYS_JSON = process.env.ARBITER_PUBKEYS_JSON;
const ARBITER_SIGNATURES_JSON = process.env.ARBITER_SIGNATURES_JSON;
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = process.env.KEY_ALGO || 'secp256k1';

const VALID_ENTRY_POINTS = ['release', 'refund', 'dispute'];

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
  if (!ENTRY_POINT || !VALID_ENTRY_POINTS.includes(ENTRY_POINT)) fail(`ENTRY_POINT must be one of: ${VALID_ENTRY_POINTS.join(', ')}`);
  if (!SERVICE_HASH || SERVICE_HASH.length !== 64) fail('SERVICE_HASH missing or invalid');
  if (!PEM_PATH) fail('PEM_PATH missing');
  if (!fs.existsSync(PEM_PATH)) fail(`PEM file not found: ${PEM_PATH}`);

  const argsMap = { service_hash: CLValue.newCLString(SERVICE_HASH) };
  if (ENTRY_POINT === 'release') {
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
    .payment(5_000_000_000) // 5 CSPR — proven sufficient
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

main().catch(err => fail(err?.message || String(err)));
