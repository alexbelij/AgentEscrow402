/**
 * cep78_transfer.mjs — Call the CEP-78 `transfer` entry point (Ordinal
 * identifier mode: token_id is a plain u64 index), to verify real on-chain
 * NFT transfer for AE402 B1.
 *
 * Env vars:
 *   CONTRACT_HASH  — 64-char hex CEP-78 contract hash
 *   TOKEN_ID       — u64 ordinal token id (string)
 *   SOURCE_HEX     — 64-char hex account hash of current owner
 *   TARGET_HEX     — 64-char hex account hash of recipient
 *   PEM_PATH       — PEM private key of the current owner/caller
 *   KEY_ALGO       — "secp256k1" (default) or "ed25519"
 *   CASPER_RPC     — RPC URL
 */
import fs from 'fs';
import sdk from 'casper-js-sdk';

const { PrivateKey, KeyAlgorithm, ContractCallBuilder, RpcClient, HttpHandler, Args, CLValue, Key } = sdk;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const CONTRACT_HASH = process.env.CONTRACT_HASH;
const TOKEN_ID = process.env.TOKEN_ID;
const SOURCE_HEX = process.env.SOURCE_HEX;
const TARGET_HEX = process.env.TARGET_HEX;
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = process.env.KEY_ALGO || 'secp256k1';

function fail(msg) {
  process.stdout.write(JSON.stringify({ success: false, error: msg }) + '\n');
  process.exit(1);
}

async function main() {
  if (!CONTRACT_HASH || CONTRACT_HASH.length !== 64) fail('CONTRACT_HASH missing/invalid');
  if (TOKEN_ID === undefined) fail('TOKEN_ID missing');
  if (!SOURCE_HEX || SOURCE_HEX.length !== 64) fail('SOURCE_HEX missing/invalid');
  if (!TARGET_HEX || TARGET_HEX.length !== 64) fail('TARGET_HEX missing/invalid');
  if (!PEM_PATH) fail('PEM_PATH missing');

  const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  const sk = await PrivateKey.fromPem(fs.readFileSync(PEM_PATH, 'utf8'), algo);

  const sourceKey = CLValue.newCLKey(Key.newKey(`account-hash-${SOURCE_HEX}`));
  const targetKey = CLValue.newCLKey(Key.newKey(`account-hash-${TARGET_HEX}`));

  const tx = new ContractCallBuilder()
    .byHash(CONTRACT_HASH)
    .entryPoint('transfer')
    .runtimeArgs(Args.fromMap({
      token_id: CLValue.newCLUint64(TOKEN_ID),
      source_key: sourceKey,
      target_key: targetKey,
    }))
    .from(sk.publicKey)
    .chainName('casper-test')
    .payment(30_000_000_000) // 30 CSPR
    .build();

  await tx.sign(sk);
  const client = new RpcClient(new HttpHandler(RPC));
  const res = await client.putTransaction(tx);
  const hash = res.transactionHash?.toHex?.() || JSON.stringify(res.transactionHash);
  process.stdout.write(JSON.stringify({ success: true, hash }) + '\n');
}

main().catch((e) => fail(e.message || String(e)));
