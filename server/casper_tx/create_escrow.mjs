/**
 * create_escrow.mjs — Submit a session-wasm create escrow tx on Casper 2.0.
 *
 * Reads config from env vars (set by casper_client.py):
 *   CONTRACT_HASH   — 64-char hex escrow contract hash
 *   RECEIVER_HEX    — 64-char hex account hash of the receiver
 *   AMOUNT_MOTES    — escrow amount in motes (string)
 *   SERVICE_HASH    — 64-char hex service identifier
 *   TTL_SECS        — escrow TTL in seconds
 *   PEM_PATH        — path to deployer PEM private key
 *   KEY_ALGO        — "secp256k1" (default) or "ed25519"
 *   CASPER_RPC      — RPC URL (default: https://node.testnet.casper.network/rpc)
 *   WASM_PATH       — path to escrow_funder.wasm (default: same dir as this script)
 *
 * Outputs JSON to stdout:  {"hash": "...", "success": true}
 * Exits non-zero on error; JSON with success:false and error field.
 */

import fs from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';
import sdk from 'casper-js-sdk';

const { PrivateKey, KeyAlgorithm, SessionBuilder, RpcClient, HttpHandler, Args, CLValue } = sdk;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const CONTRACT_HASH = process.env.CONTRACT_HASH;
const RECEIVER_HEX = process.env.RECEIVER_HEX;
const AMOUNT_MOTES = process.env.AMOUNT_MOTES;
const SERVICE_HASH = process.env.SERVICE_HASH;
const TTL_SECS = parseInt(process.env.TTL_SECS || '300', 10);
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = process.env.KEY_ALGO || 'secp256k1';

const __dir = path.dirname(fileURLToPath(import.meta.url));
const WASM_PATH = process.env.WASM_PATH || path.join(__dir, 'escrow_funder.wasm');

function fail(msg) {
  process.stdout.write(JSON.stringify({ success: false, error: msg }) + '\n');
  process.exit(1);
}

async function main() {
  // Validate inputs
  if (!CONTRACT_HASH || CONTRACT_HASH.length !== 64) fail('CONTRACT_HASH missing or invalid');
  if (!RECEIVER_HEX || RECEIVER_HEX.length !== 64) fail('RECEIVER_HEX missing or invalid');
  if (!AMOUNT_MOTES) fail('AMOUNT_MOTES missing');
  if (!SERVICE_HASH || SERVICE_HASH.length !== 64) fail('SERVICE_HASH missing or invalid');
  if (!PEM_PATH) fail('PEM_PATH missing');
  if (!fs.existsSync(PEM_PATH)) fail(`PEM file not found: ${PEM_PATH}`);
  if (!fs.existsSync(WASM_PATH)) fail(`WASM file not found: ${WASM_PATH}`);

  const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  const sk = PrivateKey.fromPem(fs.readFileSync(PEM_PATH, 'utf8'), algo);
  const wasm = new Uint8Array(fs.readFileSync(WASM_PATH));

  const args = Args.fromMap({
    contract: CLValue.newCLByteArray(Buffer.from(CONTRACT_HASH, 'hex')),
    receiver: CLValue.newCLByteArray(Buffer.from(RECEIVER_HEX, 'hex')),
    amount: CLValue.newCLUInt512(AMOUNT_MOTES),
    service_hash: CLValue.newCLString(SERVICE_HASH),
    ttl: CLValue.newCLUint64(TTL_SECS),
  });

  const tx = new SessionBuilder()
    .from(sk.publicKey)
    .wasm(wasm)
    .runtimeArgs(args)
    .chainName('casper-test')
    .payment(12_000_000_000) // 12 CSPR — proven sufficient
    .build();

  await tx.sign(sk);
  const client = new RpcClient(new HttpHandler(RPC));
  const res = await client.putTransaction(tx);
  const hash = res.transactionHash?.toHex?.() || JSON.stringify(res.transactionHash);

  process.stdout.write(JSON.stringify({ success: true, hash }) + '\n');
}

main().catch(err => fail(err?.message || String(err)));
