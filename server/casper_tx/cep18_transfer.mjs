/**
 * cep18_transfer.mjs — Call "transfer" entry point on a deployed CEP-18
 * contract, to verify real on-chain token transfer for AE402 B1.
 *
 * Env vars:
 *   CONTRACT_HASH  — 64-char hex CEP-18 contract hash
 *   RECIPIENT_HEX  — 64-char hex account hash of recipient
 *   AMOUNT         — token amount in smallest units (string)
 *   PEM_PATH       — sender PEM private key (the token holder)
 *   KEY_ALGO       — "secp256k1" (default) or "ed25519"
 *   CASPER_RPC     — RPC URL
 */
import fs from 'fs';
import sdk from 'casper-js-sdk';

const { PrivateKey, KeyAlgorithm, ContractCallBuilder, RpcClient, HttpHandler, Args, CLValue, Key } = sdk;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const CONTRACT_HASH = process.env.CONTRACT_HASH;
const RECIPIENT_HEX = process.env.RECIPIENT_HEX;
const AMOUNT = process.env.AMOUNT;
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = process.env.KEY_ALGO || 'secp256k1';

function fail(msg) {
  process.stdout.write(JSON.stringify({ success: false, error: msg }) + '\n');
  process.exit(1);
}

async function main() {
  if (!CONTRACT_HASH || CONTRACT_HASH.length !== 64) fail('CONTRACT_HASH missing/invalid');
  if (!RECIPIENT_HEX || RECIPIENT_HEX.length !== 64) fail('RECIPIENT_HEX missing/invalid');
  if (!AMOUNT) fail('AMOUNT missing');
  if (!PEM_PATH) fail('PEM_PATH missing');

  const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  const sk = await PrivateKey.fromPem(fs.readFileSync(PEM_PATH, 'utf8'), algo);

  const recipientKey = CLValue.newCLKey(Key.newKey(`account-hash-${RECIPIENT_HEX}`));

  const tx = new ContractCallBuilder()
    .byHash(CONTRACT_HASH)
    .entryPoint('transfer')
    .runtimeArgs(Args.fromMap({
      recipient: recipientKey,
      amount: CLValue.newCLUInt256(AMOUNT),
    }))
    .from(sk.publicKey)
    .chainName('casper-test')
    .payment(10_000_000_000) // 10 CSPR
    .build();

  await tx.sign(sk);
  const client = new RpcClient(new HttpHandler(RPC));
  const res = await client.putTransaction(tx);
  const hash = res.transactionHash?.toHex?.() || JSON.stringify(res.transactionHash);
  process.stdout.write(JSON.stringify({ success: true, hash }) + '\n');
}

main().catch((e) => fail(e.message || String(e)));
