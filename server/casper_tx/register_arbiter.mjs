/**
 * register_arbiter.mjs — Runs arbiter-registrar.wasm as session code to
 * register a new arbiter (with a real staked purse) on the vrf-arbiter
 * contract's `register_arbiter()` entry point.
 *
 * Sidesteps the same purse-access-rights-stripped-over-RPC gotcha as
 * fund_pool.mjs / create_escrow.mjs (see contracts/arbiter-registrar/src/main.rs).
 *
 * Env vars:
 *   WASM_PATH               — path to arbiter-registrar.wasm
 *   PACKAGE_HASH            — 64-hex vrf-arbiter package hash (no prefix)
 *   ACCOUNT_HEX             — 64-hex account hash of the arbiter being registered
 *   STAKE_MOTES             — motes to stake (pulled from the caller's own main purse)
 *   PEM_PATH / KEY_ALGO     — funder/caller account key
 *   CASPER_RPC / CSPR_CLOUD_API_KEY
 *   PAYMENT_MOTES           — deploy payment (default 50 CSPR)
 *
 * Outputs JSON to stdout:  {"hash": "...", "success": true}
 * Exits non-zero on error.
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
const ACCOUNT_HEX = process.env.ACCOUNT_HEX;
const STAKE_MOTES = process.env.STAKE_MOTES;
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
  if (!ACCOUNT_HEX || ACCOUNT_HEX.length !== 64) fail('ACCOUNT_HEX missing/invalid');
  if (!STAKE_MOTES) fail('STAKE_MOTES required');
  if (!PEM_PATH) fail('PEM_PATH required');

  const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  const sk = await PrivateKey.fromPem(fs.readFileSync(PEM_PATH, 'utf8'), algo);
  const wasm = new Uint8Array(fs.readFileSync(WASM_PATH));

  const header = DeployHeader.default();
  header.account = sk.publicKey;
  header.chainName = CHAIN_NAME;
  header.ttl = new Duration(TTL_MS);
  header.gasPrice = 1;

  // NOTE: outer deploy session arg is "stake_amount", not "stake" -- see
  // contracts/arbiter-registrar/src/main.rs for why ("stake" as a top-level
  // session arg name empirically trips Mint error 21 UnapprovedSpendingAmount
  // on live testnet).
  const args = Args.fromMap({
    contract_package_hash: CLValue.newCLString(PACKAGE_HASH),
    account: CLValue.newCLByteArray(Buffer.from(ACCOUNT_HEX, 'hex')),
    amount: CLValue.newCLUInt512(STAKE_MOTES),
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
