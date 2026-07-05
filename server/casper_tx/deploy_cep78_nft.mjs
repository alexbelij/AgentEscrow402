/**
 * deploy_cep78_nft.mjs — Install a real CEP-78 enhanced NFT contract on
 * testnet (official casper-ecosystem/cep-78-enhanced-nft wasm, built from
 * source with its pinned nightly-2025-02-04 toolchain -- same approach used
 * for the CEP-18 fungible token, see deploy_cep18_token.mjs), for AE402's
 * MultiAssetEscrow (B1) real on-chain integration (replacing the fully
 * simulated Cep78Adapter in server/multi_asset.py).
 *
 * Env vars:
 *   WASM_PATH          — path to cep78.wasm
 *   PEM_PATH           — deployer PEM private key
 *   KEY_ALGO           — "secp256k1" (default) or "ed25519"
 *   CASPER_RPC         — RPC URL
 *   PAYMENT_MOTES      — payment in motes (default 500 CSPR)
 *   COLLECTION_NAME    — e.g. "AE402 Test NFT"
 *   COLLECTION_SYMBOL  — e.g. "AETNFT"
 *   TOTAL_TOKEN_SUPPLY — e.g. 1000
 *
 * Modality choices (kept deliberately simple for the demo):
 *   ownership_mode=Transferable(2), minting_mode=Public(1), nft_kind=Digital(1),
 *   holder_mode=Mixed(2, default), base_metadata_kind=CEP78(0, built-in schema
 *   so no json_schema needed), identifier_mode=Ordinal(0), metadata_mutability=
 *   Immutable(0), allow_minting=true.
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
const PAYMENT = process.env.PAYMENT_MOTES || '500000000000';
const CHAIN_NAME = 'casper-test';
const TTL_MS = 1800000;

const COLLECTION_NAME = process.env.COLLECTION_NAME || 'AE402 Test NFT';
const COLLECTION_SYMBOL = process.env.COLLECTION_SYMBOL || 'AETNFT';
const TOTAL_TOKEN_SUPPLY = process.env.TOTAL_TOKEN_SUPPLY || '1000';

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
    collection_name: CLValue.newCLString(COLLECTION_NAME),
    collection_symbol: CLValue.newCLString(COLLECTION_SYMBOL),
    total_token_supply: CLValue.newCLUint64(TOTAL_TOKEN_SUPPLY),
    ownership_mode: CLValue.newCLUint8(2), // Transferable
    minting_mode: CLValue.newCLUint8(1), // Public
    nft_kind: CLValue.newCLUint8(1), // Digital
    holder_mode: CLValue.newCLUint8(2), // Mixed
    nft_metadata_kind: CLValue.newCLUint8(0), // CEP78 built-in schema
    identifier_mode: CLValue.newCLUint8(0), // Ordinal
    metadata_mutability: CLValue.newCLUint8(0), // Immutable
    allow_minting: CLValue.newCLValueBool(true),
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
  process.stdout.write(JSON.stringify({
    success: true,
    hash: res.deployHash,
    collection_name: COLLECTION_NAME,
    collection_symbol: COLLECTION_SYMBOL,
  }) + '\n');
}

main().catch((e) => fail(e.message || String(e)));
