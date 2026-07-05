/**
 * admin_ops.mjs — Submit installer-only administrative tx via
 * ContractCallBuilder: configure_fee | set_release_cap | set_arbiters |
 * emergency_freeze.
 *
 * All four entry points on-chain revert with ERR_UNAUTHORIZED unless the
 * transaction's signing key is the contract's installer account -- this
 * script does not enforce that itself, it only submits what it's told to.
 * The API layer (server/admin_api.py) is responsible for restricting who
 * may reach this script (see ADMIN_API_KEY check there).
 *
 * Env vars:
 *   CONTRACT_HASH        — 64-char hex escrow contract hash
 *   ENTRY_POINT          — "configure_fee" | "set_release_cap" | "set_arbiters" | "emergency_freeze"
 *   NEW_FEE_BPS          — (configure_fee only) new insurance fee, basis points, <= 1000 (10%)
 *   NEW_CAP_MOTES        — (set_release_cap only) new A1 release cap, in motes
 *   ARBITERS_JSON        — (set_arbiters only) JSON array of hex-encoded arbiter public
 *                          keys; REPLACES the whole on-chain arbiter_list
 *   PEM_PATH             — path to installer PEM private key
 *   KEY_ALGO             — "secp256k1" (default) or "ed25519"
 *   CASPER_RPC           — RPC URL (default: https://node.testnet.casper.network/rpc)
 *
 * Outputs JSON to stdout: {"hash": "...", "success": true}
 * Exits non-zero on error.
 */

import fs from 'fs';
import sdk from 'casper-js-sdk';

const { PrivateKey, KeyAlgorithm, ContractCallBuilder, RpcClient, HttpHandler, Args, CLValue } = sdk;
const CLTypeString = sdk.default ? sdk.default.CLTypeString : sdk.CLTypeString;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const CONTRACT_HASH = process.env.CONTRACT_HASH;
const ENTRY_POINT = process.env.ENTRY_POINT;
const NEW_FEE_BPS = process.env.NEW_FEE_BPS;
const NEW_CAP_MOTES = process.env.NEW_CAP_MOTES;
const ARBITERS_JSON = process.env.ARBITERS_JSON;
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = process.env.KEY_ALGO || 'secp256k1';

const VALID_ENTRY_POINTS = ['configure_fee', 'set_release_cap', 'set_arbiters', 'emergency_freeze'];

function fail(msg) {
  process.stdout.write(JSON.stringify({ success: false, error: msg }) + '\n');
  process.exit(1);
}

async function main() {
  if (!CONTRACT_HASH || CONTRACT_HASH.length !== 64) fail('CONTRACT_HASH missing or invalid');
  if (!ENTRY_POINT || !VALID_ENTRY_POINTS.includes(ENTRY_POINT)) fail(`ENTRY_POINT must be one of: ${VALID_ENTRY_POINTS.join(', ')}`);
  if (!PEM_PATH) fail('PEM_PATH missing');
  if (!fs.existsSync(PEM_PATH)) fail(`PEM file not found: ${PEM_PATH}`);

  const argsMap = {};
  if (ENTRY_POINT === 'configure_fee') {
    if (NEW_FEE_BPS === undefined) fail('NEW_FEE_BPS required for configure_fee');
    argsMap.new_fee_bps = CLValue.newCLUint64(BigInt(NEW_FEE_BPS));
  } else if (ENTRY_POINT === 'set_release_cap') {
    if (NEW_CAP_MOTES === undefined) fail('NEW_CAP_MOTES required for set_release_cap');
    argsMap.new_cap_motes = CLValue.newCLUint64(BigInt(NEW_CAP_MOTES));
  } else if (ENTRY_POINT === 'set_arbiters') {
    let arbiters;
    try {
      arbiters = JSON.parse(ARBITERS_JSON);
      if (!Array.isArray(arbiters) || arbiters.length === 0) throw new Error('empty');
    } catch {
      fail('ARBITERS_JSON must be a non-empty JSON array of hex-encoded arbiter public keys');
    }
    argsMap.arbiters = CLValue.newCLList(CLTypeString, arbiters.map(a => CLValue.newCLString(a)));
  }
  // emergency_freeze takes no arguments.

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

main().catch(err => fail(err?.message || String(err)));
