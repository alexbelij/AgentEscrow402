/**
 * id_registry_stake.mjs — Submit register_agent/add_stake via session-wasm
 * (id_registry_funder.wasm), same purse-rights-preserving pattern as
 * create_escrow.mjs / pool-funder.
 *
 * Env:
 *   PACKAGE_HASH     — 64-hex agent-identity-registry package hash (no "hash-" prefix)
 *   ENTRY_POINT      — "register_agent" | "add_stake"
 *   AMOUNT_MOTES     — stake amount in motes (string)
 *   CAPABILITIES_JSON — JSON array of capability strings (register_agent only; [] ok for add_stake)
 *   PEM_PATH, KEY_ALGO, CASPER_RPC, CSPR_CLOUD_API_KEY, WASM_PATH (optional override)
 */
import fs from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';
import sdk from 'casper-js-sdk';

const { PrivateKey, KeyAlgorithm, SessionBuilder, RpcClient, HttpHandler, Args, CLValue } = sdk;
const CLTypeString = sdk.default ? sdk.default.CLTypeString : sdk.CLTypeString;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const PACKAGE_HASH = process.env.PACKAGE_HASH;
const ENTRY_POINT = process.env.ENTRY_POINT;
const AMOUNT_MOTES = process.env.AMOUNT_MOTES;
const CAPABILITIES_JSON = process.env.CAPABILITIES_JSON || '[]';
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = process.env.KEY_ALGO || 'secp256k1';

const __dir = path.dirname(fileURLToPath(import.meta.url));
const WASM_PATH = process.env.WASM_PATH || path.join(__dir, 'id_registry_funder.wasm');

function fail(msg) {
  process.stdout.write(JSON.stringify({ success: false, error: msg }) + '\n');
  process.exit(1);
}

async function main() {
  if (!PACKAGE_HASH || PACKAGE_HASH.length !== 64) fail('PACKAGE_HASH missing or invalid');
  if (!['register_agent', 'add_stake'].includes(ENTRY_POINT)) fail('ENTRY_POINT must be register_agent or add_stake');
  if (!AMOUNT_MOTES) fail('AMOUNT_MOTES missing');
  if (!PEM_PATH) fail('PEM_PATH missing');
  if (!fs.existsSync(PEM_PATH)) fail(`PEM file not found: ${PEM_PATH}`);
  if (!fs.existsSync(WASM_PATH)) fail(`WASM file not found: ${WASM_PATH}`);

  let capabilities;
  try {
    capabilities = JSON.parse(CAPABILITIES_JSON);
    if (!Array.isArray(capabilities)) throw new Error('not array');
  } catch {
    fail('CAPABILITIES_JSON must be a JSON array of strings');
  }

  const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  const sk = await PrivateKey.fromPem(fs.readFileSync(PEM_PATH, 'utf8'), algo);
  const wasm = new Uint8Array(fs.readFileSync(WASM_PATH));

  const args = Args.fromMap({
    contract_package_hash: CLValue.newCLString(PACKAGE_HASH),
    entry_point: CLValue.newCLString(ENTRY_POINT),
    amount: CLValue.newCLUInt512(AMOUNT_MOTES),
    capabilities: CLValue.newCLList(CLTypeString, capabilities.map(c => CLValue.newCLString(c))),
  });

  const tx = new SessionBuilder()
    .from(sk.publicKey)
    .wasm(wasm)
    .runtimeArgs(args)
    .chainName('casper-test')
    .payment(15_000_000_000) // 15 CSPR — cross-contract call + storage write
    .build();

  await tx.sign(sk);
  const handler = new HttpHandler(RPC);
  if (process.env.CSPR_CLOUD_API_KEY) {
    handler.setCustomHeaders({ Authorization: process.env.CSPR_CLOUD_API_KEY });
  }
  const client = new RpcClient(handler);
  const res = await client.putTransaction(tx);
  const hash = res.transactionHash?.toHex?.() || JSON.stringify(res.transactionHash);

  process.stdout.write(JSON.stringify({ success: true, hash }) + '\n');
}

main().catch(err => fail(err?.message || String(err)));
