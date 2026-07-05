/**
 * deploy_contract_legacy.mjs — Deploy contract using Casper LEGACY Deploy API.
 *
 * Env vars:
 *   WASM_PATH     — path to .wasm file
 *   PEM_PATH      — deployer private key PEM
 *   KEY_ALGO      — "secp256k1" or "ed25519"
 *   CASPER_RPC    — RPC URL  
 *   PAYMENT_MOTES — payment in motes (default 100 CSPR)
 *   CONTRACT_NAME — label for output
 */
import fs from 'fs';
import sdk from 'casper-js-sdk';

const {
  PrivateKey,
  KeyAlgorithm,
  RpcClient,
  HttpHandler,
  DeployHeader,
  Deploy,
  ExecutableDeployItem,
  Duration,
  Args,
} = sdk;

const RPC           = process.env.CASPER_RPC   || 'https://node.testnet.casper.network/rpc';
const WASM_PATH     = process.env.WASM_PATH;
const PEM_PATH      = process.env.PEM_PATH;
const KEY_ALGO      = (process.env.KEY_ALGO || 'secp256k1').toLowerCase();
const PAYMENT       = process.env.PAYMENT_MOTES || '100000000000';
const CONTRACT_NAME = process.env.CONTRACT_NAME || 'unknown';
const CHAIN_NAME    = 'casper-test';
const TTL_MS        = 1800000;

function fail(msg) {
  process.stdout.write(JSON.stringify({ success: false, error: msg, contract_name: CONTRACT_NAME }) + '\n');
  process.exit(1);
}

async function main() {
  if (!WASM_PATH) fail('WASM_PATH is required');
  if (!PEM_PATH)  fail('PEM_PATH is required');

  const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  const pem  = fs.readFileSync(PEM_PATH, 'utf8');
  const wasm = new Uint8Array(fs.readFileSync(WASM_PATH));

  const sk = await PrivateKey.fromPem(pem, algo);

  const header     = DeployHeader.default();
  header.account   = sk.publicKey;
  header.chainName = CHAIN_NAME;
  header.ttl       = new Duration(TTL_MS);
  header.gasPrice  = 1;

  const payment = ExecutableDeployItem.standardPayment(PAYMENT);
  const session  = ExecutableDeployItem.newModuleBytes(wasm, new Args([]));
  const deploy   = Deploy.makeDeploy(header, payment, session);

  // Sign using deploy.sign(privateKey) — the SDK's built-in method
  await deploy.sign(sk);

  // Submit. node.testnet.cspr.cloud requires an Authorization header
  // (CSPR_CLOUD_API_KEY) -- without it the RPC returns 401 Unauthorized.
  const handler = new HttpHandler(RPC);
  if (process.env.CSPR_CLOUD_API_KEY) {
    handler.setCustomHeaders({ Authorization: process.env.CSPR_CLOUD_API_KEY });
  }
  const client = new RpcClient(handler);
  const result = await client.putDeploy(deploy);

  const txHash = typeof result === 'string'
    ? result
    : result?.deployHash ?? JSON.stringify(result);

  process.stdout.write(JSON.stringify({
    success: true,
    hash: txHash,
    contract_name: CONTRACT_NAME,
    format: 'legacy_deploy',
    wasm_size_bytes: wasm.length,
  }) + '\n');
}

main().catch(err => fail(err?.message || String(err)));
