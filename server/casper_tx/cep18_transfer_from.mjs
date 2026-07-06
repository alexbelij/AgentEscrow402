/**
 * cep18_transfer_from.mjs — Call the standard CEP-18 "transfer_from" entry
 * point (moves tokens using an existing allowance, e.g. one just granted
 * via permit()). Submitted+paid by whichever account is the approved
 * `spender` (or an operator acting for it) — this is the second half of
 * the AE402 "gasless permit deposit" flow: permit() (owner's signature,
 * relayer pays gas) followed immediately by transfer_from() (relayer/
 * spender pulls the funds using the just-granted allowance).
 *
 * Env vars:
 *   CONTRACT_HASH — 64-char hex CEP-18 contract hash
 *   OWNER_ACCOUNT_HASH — 64-char hex account hash of the token owner
 *   RECIPIENT_ACCOUNT_HASH — 64-char hex account hash receiving the tokens
 *   AMOUNT — token amount, smallest units (string)
 *   PEM_PATH — spender's own PEM (must match the `spender` used in permit())
 *   KEY_ALGO — "secp256k1" (default) or "ed25519"
 *   CASPER_RPC — RPC URL
 */
import fs from 'fs';
import sdk from 'casper-js-sdk';

const {
  PrivateKey, KeyAlgorithm, ContractCallBuilder, RpcClient, HttpHandler, Args, CLValue, Key,
} = sdk;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const CONTRACT_HASH = process.env.CONTRACT_HASH;
const OWNER_ACCOUNT_HASH = process.env.OWNER_ACCOUNT_HASH;
const RECIPIENT_ACCOUNT_HASH = process.env.RECIPIENT_ACCOUNT_HASH;
const AMOUNT = process.env.AMOUNT;
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = process.env.KEY_ALGO || 'secp256k1';

function fail(msg) {
  process.stdout.write(JSON.stringify({ success: false, error: msg }) + '\n');
  process.exit(1);
}

async function main() {
  if (!CONTRACT_HASH || CONTRACT_HASH.length !== 64) fail('CONTRACT_HASH missing/invalid');
  if (!OWNER_ACCOUNT_HASH || OWNER_ACCOUNT_HASH.length !== 64) fail('OWNER_ACCOUNT_HASH missing/invalid');
  if (!RECIPIENT_ACCOUNT_HASH || RECIPIENT_ACCOUNT_HASH.length !== 64) fail('RECIPIENT_ACCOUNT_HASH missing/invalid');
  if (!AMOUNT) fail('AMOUNT missing');
  if (!PEM_PATH) fail('PEM_PATH missing');

  const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  const sk = await PrivateKey.fromPem(fs.readFileSync(PEM_PATH, 'utf8'), algo);

  const ownerKey = CLValue.newCLKey(Key.newKey(`account-hash-${OWNER_ACCOUNT_HASH}`));
  const recipientKey = CLValue.newCLKey(Key.newKey(`account-hash-${RECIPIENT_ACCOUNT_HASH}`));

  const tx = new ContractCallBuilder()
    .byHash(CONTRACT_HASH)
    .entryPoint('transfer_from')
    .runtimeArgs(Args.fromMap({
      owner: ownerKey,
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
