/**
 * select_arbiters.mjs — Submit `select_arbiters` tx against the vrf-arbiter
 * contract (on-chain VRF election of arbiters for a dispute).
 *
 * No purse arg needed (unlike register_arbiter), so this uses a plain
 * ContractCallBuilder deploy against the contract by hash, same pattern as
 * resolve.mjs / set_arbiters.mjs.
 *
 * Env vars:
 *   CONTRACT_HASH   — 64-hex vrf-arbiter contract hash (no prefix)
 *   DISPUTE_ID      — string dispute identifier (must not already have an
 *                     election recorded, or the contract reverts
 *                     ERR_ELECTION_EXISTS=5)
 *   COUNT           — number of arbiters to select (u64)
 *   PEM_PATH / KEY_ALGO — submitter key (any account may call; the
 *                     selection itself has no authorization check)
 *   CASPER_RPC / CSPR_CLOUD_API_KEY
 *
 * Outputs JSON to stdout: {"hash": "...", "success": true}
 * Exits non-zero on error.
 */
import fs from 'fs';
import sdk from 'casper-js-sdk';

const { PrivateKey, KeyAlgorithm, ContractCallBuilder, RpcClient, HttpHandler, Args, CLValue } = sdk;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const CONTRACT_HASH = process.env.CONTRACT_HASH;
const DISPUTE_ID = process.env.DISPUTE_ID;
const COUNT = process.env.COUNT;
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = process.env.KEY_ALGO || 'secp256k1';

function fail(msg) {
  process.stdout.write(JSON.stringify({ success: false, error: msg }) + '\n');
  process.exit(1);
}

async function main() {
  if (!CONTRACT_HASH || CONTRACT_HASH.length !== 64) fail('CONTRACT_HASH missing or invalid');
  if (!DISPUTE_ID) fail('DISPUTE_ID missing');
  if (!COUNT) fail('COUNT missing');
  if (!PEM_PATH) fail('PEM_PATH missing');
  if (!fs.existsSync(PEM_PATH)) fail(`PEM file not found: ${PEM_PATH}`);

  const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  const sk = PrivateKey.fromPem(fs.readFileSync(PEM_PATH, 'utf8'), algo);

  const tx = new ContractCallBuilder()
    .byHash(CONTRACT_HASH)
    .entryPoint('select_arbiters')
    .runtimeArgs(Args.fromMap({
      dispute_id: CLValue.newCLString(DISPUTE_ID),
      count: CLValue.newCLUint64(BigInt(COUNT)),
    }))
    .from(sk.publicKey)
    .chainName('casper-test')
    .payment(5_000_000_000) // 5 CSPR — dict write only, no transfer
    .build();

  await tx.sign(sk);
  const handler = new HttpHandler(RPC);
  if (process.env.CSPR_CLOUD_API_KEY) handler.setCustomHeaders({ Authorization: process.env.CSPR_CLOUD_API_KEY });
  const client = new RpcClient(handler);

  try {
    const res = await client.putTransaction(tx);
    const hash = res.transactionHash?.toHex?.() || JSON.stringify(res.transactionHash);
    process.stdout.write(JSON.stringify({ success: true, hash }) + '\n');
  } catch (e) {
    fail(String(e));
  }
}

main().catch(err => fail(err?.message || String(err)));
