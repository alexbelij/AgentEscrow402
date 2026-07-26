/**
 * deploy_casper_htlc.mjs — Install the casper-htlc contract on Testnet.
 *
 * Env vars (same as deploy_contract_legacy.mjs, plus two named args):
 *   WASM_PATH             — path to casper_htlc.wasm
 *   PEM_PATH              — deployer key PEM
 *   KEY_ALGO              — "secp256k1" | "ed25519" (default secp256k1)
 *   CASPER_RPC            — RPC URL (default testnet)
 *   PAYMENT_MOTES         — payment in motes (default 300 CSPR — contract install)
 *   PACKAGE_HASH_NAME     — named-key for the package (default "casper_htlc_package")
 *   CONTRACT_HASH_NAME    — named-key for the contract hash (default "casper_htlc_contract")
 *
 * Emits a single-line JSON on stdout:
 *   { success, hash, contract_name, wasm_size_bytes, format }
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
  CLValue,
} = sdk;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const WASM_PATH = process.env.WASM_PATH;
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = (process.env.KEY_ALGO || 'secp256k1').toLowerCase();
const PAYMENT = process.env.PAYMENT_MOTES || '300000000000'; // 300 CSPR
const PACKAGE_NAME = process.env.PACKAGE_HASH_NAME || 'casper_htlc_package';
const CONTRACT_NAME = process.env.CONTRACT_HASH_NAME || 'casper_htlc_contract';
const CHAIN_NAME = 'casper-test';
const TTL_MS = 1800000;

function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + '\n');
}
function fail(msg) {
  emit({ success: false, error: msg, contract_name: CONTRACT_NAME });
  process.exit(1);
}

async function main() {
  if (!WASM_PATH) fail('WASM_PATH is required');
  if (!PEM_PATH) fail('PEM_PATH is required');

  const algo =
    KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  const pem = fs.readFileSync(PEM_PATH, 'utf8');
  const wasm = new Uint8Array(fs.readFileSync(WASM_PATH));
  const sk = await PrivateKey.fromPem(pem, algo);

  const header = DeployHeader.default();
  header.account = sk.publicKey;
  header.chainName = CHAIN_NAME;
  header.ttl = new Duration(TTL_MS);
  header.gasPrice = 1;

  const args = Args.fromMap({
    package_hash_name: CLValue.newCLString(PACKAGE_NAME),
    contract_hash_name: CLValue.newCLString(CONTRACT_NAME),
  });

  const payment = ExecutableDeployItem.standardPayment(PAYMENT);
  const session = ExecutableDeployItem.newModuleBytes(wasm, args);
  const deploy = Deploy.makeDeploy(header, payment, session);

  await deploy.sign(sk);

  const handler = new HttpHandler(RPC);
  if (process.env.CSPR_CLOUD_API_KEY) {
    handler.setCustomHeaders({ Authorization: process.env.CSPR_CLOUD_API_KEY });
  }
  const client = new RpcClient(handler);
  const result = await client.putDeploy(deploy);
  const txHash =
    typeof result === 'string'
      ? result
      : result?.deployHash ?? JSON.stringify(result);

  emit({
    success: true,
    hash: txHash,
    contract_name: CONTRACT_NAME,
    package_name: PACKAGE_NAME,
    format: 'legacy_deploy',
    wasm_size_bytes: wasm.length,
  });
}

main().catch((err) => fail(err?.message || String(err)));
