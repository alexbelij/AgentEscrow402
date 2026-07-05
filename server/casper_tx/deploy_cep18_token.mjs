/**
 * deploy_cep18_token.mjs — Install a real CEP-18 fungible token contract on
 * testnet (official casper-ecosystem/cep18 v1.2.0 wasm), for AE402's
 * MultiAssetEscrow (B1) real on-chain integration (replacing the fully
 * simulated Cep18Adapter in server/multi_asset.py).
 *
 * Env vars:
 *   WASM_PATH        — path to cep18.wasm
 *   PEM_PATH         — deployer PEM private key
 *   KEY_ALGO         — "secp256k1" (default) or "ed25519"
 *   CASPER_RPC       — RPC URL
 *   PAYMENT_MOTES    — payment in motes (default 200 CSPR)
 *   TOKEN_NAME       — e.g. "AE402 Test USD"
 *   TOKEN_SYMBOL     — e.g. "AETUSD"
 *   TOKEN_DECIMALS   — e.g. 6
 *   TOKEN_TOTAL_SUPPLY — in smallest units (string)
 */
import fs from 'fs';
import sdk from 'casper-js-sdk';

const {
  PrivateKey, KeyAlgorithm, RpcClient, HttpHandler,
  DeployHeader, Deploy, ExecutableDeployItem, Duration, Args, CLValue,
} = sdk;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const WASM_PATH = process.env.WASM_PATH;
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = (process.env.KEY_ALGO || 'secp256k1').toLowerCase();
const PAYMENT = process.env.PAYMENT_MOTES || '200000000000';
const CHAIN_NAME = 'casper-test';
const TTL_MS = 1800000;

const TOKEN_NAME = process.env.TOKEN_NAME || 'AE402 Test USD';
const TOKEN_SYMBOL = process.env.TOKEN_SYMBOL || 'AETUSD';
const TOKEN_DECIMALS = parseInt(process.env.TOKEN_DECIMALS || '6', 10);
const TOKEN_TOTAL_SUPPLY = process.env.TOKEN_TOTAL_SUPPLY || '1000000000000'; // 1,000,000.000000

function fail(msg) {
  process.stdout.write(JSON.stringify({ success: false, error: msg }) + '\n');
  process.exit(1);
}

async function main() {
  if (!WASM_PATH) fail('WASM_PATH required');
  if (!PEM_PATH) fail('PEM_PATH required');
  if (!fs.existsSync(WASM_PATH)) fail(`wasm not found: ${WASM_PATH}`);

  const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  const sk = await PrivateKey.fromPem(fs.readFileSync(PEM_PATH, 'utf8'), algo);
  const wasm = new Uint8Array(fs.readFileSync(WASM_PATH));

  const args = Args.fromMap({
    name: CLValue.newCLString(TOKEN_NAME),
    symbol: CLValue.newCLString(TOKEN_SYMBOL),
    decimals: CLValue.newCLUint8(TOKEN_DECIMALS),
    total_supply: CLValue.newCLUInt256(TOKEN_TOTAL_SUPPLY),
    enable_mint_burn: CLValue.newCLUint8(1),
  });

  const header = DeployHeader.default();
  header.account = sk.publicKey;
  header.chainName = CHAIN_NAME;
  header.ttl = new Duration(TTL_MS);
  header.gasPrice = 1;

  const payment = ExecutableDeployItem.standardPayment(PAYMENT);
  const session = ExecutableDeployItem.newModuleBytes(wasm, args);
  const deploy = Deploy.makeDeploy(header, payment, session);
  await deploy.sign(sk);

  const client = new RpcClient(new HttpHandler(RPC));
  const res = await client.putDeploy(deploy);
  process.stdout.write(JSON.stringify({ success: true, hash: res.deployHash, token_name: TOKEN_NAME, token_symbol: TOKEN_SYMBOL }) + '\n');
}

main().catch((e) => fail(e.message || String(e)));
