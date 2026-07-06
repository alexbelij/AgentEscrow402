/**
 * cep18_permit.mjs — Call the AE402 CEP-2612-inspired "permit" entry point
 * on our forked CEP-18 contract (see contracts fork history in
 * skills/integrations/casper/SKILL.md). Anyone may submit this (a relayer,
 * here: the AE402 backend operator key) and pay its gas; the on-chain
 * contract only grants the allowance if `signature` is a genuine Ed25519
 * signature by `owner_public_key` over the canonical message, and that
 * public key really hashes to `owner` — so the relayer can never grant an
 * allowance the owner didn't actually authorize themselves off-chain.
 *
 * Env vars:
 *   CONTRACT_HASH       — 64-char hex CEP-18 contract hash (post-permit-upgrade version)
 *   OWNER_ACCOUNT_HASH  — 64-char hex account hash of the token owner
 *   OWNER_PUBLIC_KEY    — owner's public key, hex (with algo-tag prefix byte)
 *   SPENDER_ACCOUNT_HASH — 64-char hex account hash of the spender (relayer/escrow)
 *   AMOUNT              — allowance amount, smallest units (string)
 *   DEADLINE            — unix ms deadline (string/number), must be >= on-chain blocktime
 *   SIGNATURE           — owner's Ed25519 signature, hex, over the canonical message
 *   PEM_PATH            — relayer's own PEM (pays gas; NOT the owner's key)
 *   KEY_ALGO            — relayer key algo, "secp256k1" (default) or "ed25519"
 *   CASPER_RPC          — RPC URL
 */
import fs from 'fs';
import sdk from 'casper-js-sdk';

const {
  PrivateKey, KeyAlgorithm, ContractCallBuilder, RpcClient, HttpHandler, Args, CLValue, Key,
} = sdk;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const CONTRACT_HASH = process.env.CONTRACT_HASH;
const OWNER_ACCOUNT_HASH = process.env.OWNER_ACCOUNT_HASH;
const OWNER_PUBLIC_KEY = process.env.OWNER_PUBLIC_KEY;
const SPENDER_ACCOUNT_HASH = process.env.SPENDER_ACCOUNT_HASH;
const AMOUNT = process.env.AMOUNT;
const DEADLINE = process.env.DEADLINE;
const SIGNATURE = process.env.SIGNATURE;
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = process.env.KEY_ALGO || 'secp256k1';

function fail(msg) {
  process.stdout.write(JSON.stringify({ success: false, error: msg }) + '\n');
  process.exit(1);
}

async function main() {
  if (!CONTRACT_HASH || CONTRACT_HASH.length !== 64) fail('CONTRACT_HASH missing/invalid');
  if (!OWNER_ACCOUNT_HASH || OWNER_ACCOUNT_HASH.length !== 64) fail('OWNER_ACCOUNT_HASH missing/invalid');
  if (!OWNER_PUBLIC_KEY) fail('OWNER_PUBLIC_KEY missing');
  if (!SPENDER_ACCOUNT_HASH || SPENDER_ACCOUNT_HASH.length !== 64) fail('SPENDER_ACCOUNT_HASH missing/invalid');
  if (!AMOUNT) fail('AMOUNT missing');
  if (!DEADLINE) fail('DEADLINE missing');
  if (!SIGNATURE) fail('SIGNATURE missing');
  if (!PEM_PATH) fail('PEM_PATH missing');

  const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  const relayerKey = await PrivateKey.fromPem(fs.readFileSync(PEM_PATH, 'utf8'), algo);

  const ownerKey = CLValue.newCLKey(Key.newKey(`account-hash-${OWNER_ACCOUNT_HASH}`));
  const spenderKey = CLValue.newCLKey(Key.newKey(`account-hash-${SPENDER_ACCOUNT_HASH}`));

  const tx = new ContractCallBuilder()
    .byHash(CONTRACT_HASH)
    .entryPoint('permit')
    .runtimeArgs(Args.fromMap({
      owner: ownerKey,
      owner_public_key: CLValue.newCLString(OWNER_PUBLIC_KEY),
      spender: spenderKey,
      amount: CLValue.newCLUInt256(AMOUNT),
      deadline: CLValue.newCLUint64(DEADLINE),
      signature: CLValue.newCLString(SIGNATURE),
    }))
    .from(relayerKey.publicKey)
    .chainName('casper-test')
    .payment(10_000_000_000) // 10 CSPR
    .build();

  await tx.sign(relayerKey);
  const client = new RpcClient(new HttpHandler(RPC));
  const res = await client.putTransaction(tx);
  const hash = res.transactionHash?.toHex?.() || JSON.stringify(res.transactionHash);
  process.stdout.write(JSON.stringify({ success: true, hash }) + '\n');
}

main().catch((e) => fail(e.message || String(e)));
