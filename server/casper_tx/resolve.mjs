/**
 * resolve.mjs — Submit `resolve` tx (3-of-5 arbiter multisig dispute resolution).
 *
 * Reads config from env vars:
 *   CONTRACT_HASH            — 64-char hex escrow contract hash
 *   SERVICE_HASH             — 64-char hex service identifier
 *   IN_FAVOR_OF              — "sender" | "receiver"
 *   ARBITER_PUBKEYS_JSON     — JSON array of arbiter hex-encoded Ed25519 public keys
 *                              (tag-prefixed, e.g. "01" + 32-byte hex), >= threshold
 *   ARBITER_SIGNATURES_JSON  — JSON array (same order/length) of hex-encoded Ed25519
 *                              signatures (tag-prefixed) over
 *                              "resolve:{SERVICE_HASH}:{IN_FAVOR_OF}", produced by each
 *                              arbiter's own private key (see server/arbiter_crypto.py /
 *                              examples/sign_arbiter_vote.py for the signer side)
 *   PEM_PATH                 — path to submitter PEM private key (any account may call;
 *                              only the arbiter pubkey+signature pairs are checked
 *                              on-chain, not the caller's own identity)
 *   KEY_ALGO                 — "secp256k1" (default) or "ed25519"
 *   CASPER_RPC                — RPC URL (default: https://node.testnet.casper.network/rpc)
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
const SERVICE_HASH = process.env.SERVICE_HASH;
const IN_FAVOR_OF = process.env.IN_FAVOR_OF;
const ARBITER_PUBKEYS_JSON = process.env.ARBITER_PUBKEYS_JSON;
const ARBITER_SIGNATURES_JSON = process.env.ARBITER_SIGNATURES_JSON;
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = process.env.KEY_ALGO || 'secp256k1';

function fail(msg) {
  process.stdout.write(JSON.stringify({ success: false, error: msg }) + '\n');
  process.exit(1);
}

async function main() {
  if (!CONTRACT_HASH || CONTRACT_HASH.length !== 64) fail('CONTRACT_HASH missing or invalid');
  if (!SERVICE_HASH || SERVICE_HASH.length !== 64) fail('SERVICE_HASH missing or invalid');
  if (!['sender', 'receiver'].includes(IN_FAVOR_OF)) fail('IN_FAVOR_OF must be "sender" or "receiver"');
  if (!PEM_PATH) fail('PEM_PATH missing');
  if (!fs.existsSync(PEM_PATH)) fail(`PEM file not found: ${PEM_PATH}`);

  let arbiterPubkeys;
  let arbiterSignatures;
  try {
    arbiterPubkeys = JSON.parse(ARBITER_PUBKEYS_JSON);
    if (!Array.isArray(arbiterPubkeys) || arbiterPubkeys.length === 0) throw new Error('empty');
  } catch {
    fail('ARBITER_PUBKEYS_JSON must be a JSON array of hex-encoded arbiter public keys');
  }
  try {
    arbiterSignatures = JSON.parse(ARBITER_SIGNATURES_JSON);
    if (!Array.isArray(arbiterSignatures) || arbiterSignatures.length !== arbiterPubkeys.length) {
      throw new Error('length mismatch');
    }
  } catch {
    fail('ARBITER_SIGNATURES_JSON must be a JSON array matching ARBITER_PUBKEYS_JSON in length');
  }

  const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  const sk = PrivateKey.fromPem(fs.readFileSync(PEM_PATH, 'utf8'), algo);

  const tx = new ContractCallBuilder()
    .byHash(CONTRACT_HASH)
    .entryPoint('resolve')
    .runtimeArgs(Args.fromMap({
      service_hash: CLValue.newCLString(SERVICE_HASH),
      in_favor_of: CLValue.newCLString(IN_FAVOR_OF),
      arbiter_pubkeys: CLValue.newCLList(CLTypeString, arbiterPubkeys.map(a => CLValue.newCLString(a))),
      arbiter_signatures: CLValue.newCLList(CLTypeString, arbiterSignatures.map(a => CLValue.newCLString(a))),
    }))
    .from(sk.publicKey)
    .chainName('casper-test')
    .payment(10_000_000_000) // 10 CSPR — resolve does a transfer + dict write + signature verification
    .build();

  await tx.sign(sk);
  const client = new RpcClient(new HttpHandler(RPC));
  const res = await client.putTransaction(tx);
  const hash = res.transactionHash?.toHex?.() || JSON.stringify(res.transactionHash);

  process.stdout.write(JSON.stringify({ success: true, hash }) + '\n');
}

main().catch(err => fail(err?.message || String(err)));
