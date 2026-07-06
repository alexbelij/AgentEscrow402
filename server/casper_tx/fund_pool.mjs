/**
 * fund_pool.mjs — Runs pool-funder.wasm as session code to deposit real
 * CSPR into an insurance-pool contract's purse via its `deposit()` entry
 * point, sidestepping the purse-access-rights-stripped-over-RPC gotcha
 * (see contracts/pool-funder/src/main.rs for the full explanation).
 *
 * Env vars:
 *   WASM_PATH              — path to pool-funder.wasm
 *   PACKAGE_HASH            — 64-hex insurance-pool package hash (no prefix)
 *   AMOUNT_MOTES            — motes to deposit
 *   PEM_PATH / KEY_ALGO     — funder account key
 *   CASPER_RPC / CSPR_CLOUD_API_KEY
 *   PAYMENT_MOTES           — deploy payment (default 50 CSPR, session does
 *                             a purse create + transfer + cross-contract
 *                             call so needs a bit more than a plain xfer)
 */
import fs from 'fs';
import sdk from 'casper-js-sdk';

const {
  PrivateKey, KeyAlgorithm, RpcClient, HttpHandler,
  DeployHeader, Deploy, ExecutableDeployItem, Duration, Args, CLValue,
} = sdk;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.cspr.cloud/rpc';
const WASM_PATH = process.env.WASM_PATH;
const PACKAGE_HASH = process.env.PACKAGE_HASH;
const AMOUNT_MOTES = process.env.AMOUNT_MOTES;
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = (process.env.KEY_ALGO || 'secp256k1').toLowerCase();
const PAYMENT = process.env.PAYMENT_MOTES || '50000000000';
const CHAIN_NAME = 'casper-test';
const TTL_MS = 1800000;

function fail(msg) {
  process.stdout.write(JSON.stringify({ success: false, error: msg }) + '\n');
  process.exit(1);
}

async function main() {
  if (!WASM_PATH) fail('WASM_PATH required');
  if (!PACKAGE_HASH || PACKAGE_HASH.length !== 64) fail('PACKAGE_HASH missing/invalid');
  if (!AMOUNT_MOTES) fail('AMOUNT_MOTES required');
  if (!PEM_PATH) fail('PEM_PATH required');

  const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  const sk = await PrivateKey.fromPem(fs.readFileSync(PEM_PATH, 'utf8'), algo);
  const wasm = new Uint8Array(fs.readFileSync(WASM_PATH));

  const header = DeployHeader.default();
  header.account = sk.publicKey;
  header.chainName = CHAIN_NAME;
  header.ttl = new Duration(TTL_MS);
  header.gasPrice = 1;

  const args = Args.fromMap({
    contract_package_hash: CLValue.newCLString(PACKAGE_HASH),
    amount: CLValue.newCLUInt512(AMOUNT_MOTES),
  });

  const payment = ExecutableDeployItem.standardPayment(PAYMENT);
  const session = ExecutableDeployItem.newModuleBytes(wasm, args);
  const deploy = Deploy.makeDeploy(header, payment, session);
  await deploy.sign(sk);

  const handler = new HttpHandler(RPC);
  if (process.env.CSPR_CLOUD_API_KEY) handler.setCustomHeaders({ Authorization: process.env.CSPR_CLOUD_API_KEY });
  const client = new RpcClient(handler);

  try {
    const res = await client.putDeploy(deploy);
    console.log(JSON.stringify({ success: true, hash: res.deployHash?.toHex?.() || res.deployHash || res }));
  } catch (e) {
    console.log(JSON.stringify({ success: false, error: String(e) }));
    process.exit(1);
  }
}

main();
