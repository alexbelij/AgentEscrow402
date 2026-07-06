/**
 * create_batch.mjs — Submit a session-wasm escrow-manager.create_batch() tx.
 *
 * Wires escrow-manager.create_batch() to a real on-chain call: pulls the
 * caller's own main purse funds into a fresh purse (session context, so the
 * URef keeps its access rights across the native cross-contract call — see
 * contracts/batch-funder/src/main.rs) then calls create_batch(...) with N
 * escrows in ONE deploy.
 *
 * Reads config from env vars:
 *   MANAGER_CONTRACT_HASH — 64-char hex escrow-manager contract hash
 *   RECEIVERS_JSON        — JSON array of 64-char hex account-hash strings
 *   AMOUNTS_JSON           — JSON array of motes-as-string, same length
 *   SERVICE_HASHES_JSON    — JSON array of unique 64-char hex strings, same length
 *   TTLS_JSON              — JSON array of u64 seconds, same length
 *   PEM_PATH               — path to sender PEM private key
 *   KEY_ALGO               — "secp256k1" (default) or "ed25519"
 *   CASPER_RPC             — RPC URL
 *   WASM_PATH              — path to batch_funder.wasm (default: same dir)
 *
 * Outputs JSON to stdout: {"hash": "...", "success": true, "created": N}
 */

import fs from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';
import sdk from 'casper-js-sdk';

const { PrivateKey, KeyAlgorithm, SessionBuilder, RpcClient, HttpHandler, Args, CLValue, CLTypeString, CLTypeUInt512, CLTypeUInt64 } = sdk;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const MANAGER_CONTRACT_HASH = process.env.MANAGER_CONTRACT_HASH;
const RECEIVERS = JSON.parse(process.env.RECEIVERS_JSON || '[]');
const AMOUNTS = JSON.parse(process.env.AMOUNTS_JSON || '[]');
const SERVICE_HASHES = JSON.parse(process.env.SERVICE_HASHES_JSON || '[]');
const TTLS = JSON.parse(process.env.TTLS_JSON || '[]');
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = process.env.KEY_ALGO || 'secp256k1';
const PAYMENT_MOTES = process.env.PAYMENT_MOTES || '20000000000'; // 20 CSPR ceiling for the loop

const __dir = path.dirname(fileURLToPath(import.meta.url));
const WASM_PATH = process.env.WASM_PATH || path.join(__dir, 'batch_funder.wasm');

function fail(msg) {
  process.stdout.write(JSON.stringify({ success: false, error: msg }) + '\n');
  process.exit(1);
}

async function main() {
  if (!MANAGER_CONTRACT_HASH || MANAGER_CONTRACT_HASH.length !== 64) fail('MANAGER_CONTRACT_HASH missing or invalid');
  const n = RECEIVERS.length;
  if (n === 0) fail('RECEIVERS_JSON empty');
  if (AMOUNTS.length !== n || SERVICE_HASHES.length !== n || TTLS.length !== n) fail('array length mismatch');
  if (!PEM_PATH) fail('PEM_PATH missing');
  if (!fs.existsSync(PEM_PATH)) fail(`PEM file not found: ${PEM_PATH}`);
  if (!fs.existsSync(WASM_PATH)) fail(`WASM file not found: ${WASM_PATH}`);

  const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  const sk = PrivateKey.fromPem(fs.readFileSync(PEM_PATH, 'utf8'), algo);
  const wasm = new Uint8Array(fs.readFileSync(WASM_PATH));

  // Casper 2.0 gotcha (see skills/integrations/casper/SKILL.md): the node
  // seeds this deploy's Mint "remaining_spending_limit" from a top-level
  // session arg literally named "amount" — without it any
  // transfer_from_purse_to_purse (ours: main_purse->new_purse, then the
  // manager contract's own new_purse->contract_purse per escrow) reverts
  // with "Mint error: 21 (UnapprovedSpendingAmount)".
  const total = AMOUNTS.reduce((acc, a) => acc + BigInt(a), 0n).toString();

  const args = Args.fromMap({
    amount: CLValue.newCLUInt512(total),
    manager_contract_hash: CLValue.newCLString(MANAGER_CONTRACT_HASH),
    receivers: CLValue.newCLList(CLTypeString, RECEIVERS.map((r) => CLValue.newCLString(r))),
    amounts: CLValue.newCLList(CLTypeUInt512, AMOUNTS.map((a) => CLValue.newCLUInt512(a))),
    service_hashes: CLValue.newCLList(CLTypeString, SERVICE_HASHES.map((s) => CLValue.newCLString(s))),
    ttls: CLValue.newCLList(CLTypeUInt64, TTLS.map((t) => CLValue.newCLUint64(t))),
  });

  const tx = new SessionBuilder()
    .from(sk.publicKey)
    .wasm(wasm)
    .runtimeArgs(args)
    .chainName('casper-test')
    .payment(parseInt(PAYMENT_MOTES, 10))
    .build();

  await tx.sign(sk);
  const _handler = new HttpHandler(RPC);
  if (process.env.CSPR_CLOUD_API_KEY) {
    _handler.setCustomHeaders({ Authorization: process.env.CSPR_CLOUD_API_KEY });
  }
  const client = new RpcClient(_handler);
  const res = await client.putTransaction(tx);
  const hash = res.transactionHash?.toHex?.() || JSON.stringify(res.transactionHash);

  process.stdout.write(JSON.stringify({ success: true, hash, created: n }) + '\n');
}

main().catch((err) => fail(err?.message || String(err)));
