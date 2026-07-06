/**
 * insurance_claim.mjs — Submit `claim` tx against the insurance-pool
 * contract (3-of-5 arbiter multisig payout, see contracts/insurance-pool/
 * src/main.rs `require_arbiter_quorum`).
 *
 * Env vars:
 *   CONTRACT_HASH             — 64-char hex insurance-pool contract hash
 *   ESCROW_ID                 — string identifier of the disputed escrow
 *   AMOUNT_MOTES              — claim payout amount in motes
 *   EVIDENCE                  — free-text evidence string (received, not
 *                               verified on-chain)
 *   ARBITER_PUBKEYS_JSON      — JSON array of arbiter hex-encoded Ed25519
 *                               public keys (tag-prefixed), >= threshold
 *   ARBITER_SIGNATURES_JSON   — JSON array (same order/length) of
 *                               hex-encoded Ed25519 signatures (tag-prefixed)
 *                               over "claim:{ESCROW_ID}:{caller_account_hash}:
 *                               {AMOUNT_MOTES}" -- caller_account_hash is the
 *                               account derived from PEM_PATH (this script
 *                               signs+submits the deploy, so get_caller() on
 *                               chain equals that account)
 *   PEM_PATH / KEY_ALGO       — submitter key (becomes the on-chain claimant,
 *                               i.e. payout recipient)
 *   CASPER_RPC / CSPR_CLOUD_API_KEY
 *
 * Outputs JSON to stdout: {"success": true, "hash": "..."}
 * Exits non-zero on error.
 */

import fs from 'fs';
import sdk from 'casper-js-sdk';

const { PrivateKey, KeyAlgorithm, ContractCallBuilder, RpcClient, HttpHandler, Args, CLValue } = sdk;
const CLTypeString = sdk.default ? sdk.default.CLTypeString : sdk.CLTypeString;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const CONTRACT_HASH = process.env.CONTRACT_HASH;
const ESCROW_ID = process.env.ESCROW_ID;
const AMOUNT_MOTES = process.env.AMOUNT_MOTES;
const EVIDENCE = process.env.EVIDENCE || '';
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
  if (!ESCROW_ID) fail('ESCROW_ID missing');
  if (!AMOUNT_MOTES) fail('AMOUNT_MOTES missing');
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
    .entryPoint('claim')
    .runtimeArgs(Args.fromMap({
      escrow_id: CLValue.newCLString(ESCROW_ID),
      amount: CLValue.newCLUInt512(AMOUNT_MOTES),
      evidence: CLValue.newCLString(EVIDENCE),
      arbiter_pubkeys: CLValue.newCLList(CLTypeString, arbiterPubkeys.map(a => CLValue.newCLString(a))),
      arbiter_signatures: CLValue.newCLList(CLTypeString, arbiterSignatures.map(a => CLValue.newCLString(a))),
    }))
    .from(sk.publicKey)
    .chainName('casper-test')
    .payment(10_000_000_000) // 10 CSPR — claim does a transfer + dict write + signature verification
    .build();

  await tx.sign(sk);
  const handler = new HttpHandler(RPC);
  if (process.env.CSPR_CLOUD_API_KEY) handler.setCustomHeaders({ Authorization: process.env.CSPR_CLOUD_API_KEY });
  const client = new RpcClient(handler);
  const res = await client.putTransaction(tx);
  const hash = res.transactionHash?.toHex?.() || JSON.stringify(res.transactionHash);

  process.stdout.write(JSON.stringify({ success: true, hash }) + '\n');
}

main().catch(err => fail(err?.message || String(err)));
