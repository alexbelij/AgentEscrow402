/**
 * cspr_transfer.mjs — simple native CSPR transfer.
 * Env: PEM_PATH, KEY_ALGO, TARGET_ACCOUNT_HASH, AMOUNT_MOTES, CASPER_RPC, CSPR_CLOUD_API_KEY
 */
import fs from 'fs';
import sdk from 'casper-js-sdk';

const {
  PrivateKey, KeyAlgorithm, RpcClient, HttpHandler,
  makeCsprTransferDeploy,
} = sdk;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = (process.env.KEY_ALGO || 'secp256k1').toLowerCase();
const RECIPIENT_PUBKEY_HEX = process.env.RECIPIENT_PUBKEY_HEX;
const AMOUNT = process.env.AMOUNT_MOTES || '110000000000';
const CHAIN_NAME = 'casper-test';

function fail(msg) {
  process.stdout.write(JSON.stringify({ success: false, error: msg }) + '\n');
  process.exit(1);
}

async function main() {
  if (!PEM_PATH) fail('PEM_PATH required');
  if (!RECIPIENT_PUBKEY_HEX) fail('RECIPIENT_PUBKEY_HEX required');

  const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  const pem = fs.readFileSync(PEM_PATH, 'utf8');
  const sk = await PrivateKey.fromPem(pem, algo);

  const deploy = makeCsprTransferDeploy({
    senderPublicKeyHex: sk.publicKey.toHex(),
    recipientPublicKeyHex: RECIPIENT_PUBKEY_HEX,
    transferAmount: AMOUNT,
    chainName: CHAIN_NAME,
  });
  await deploy.sign(sk);

  const handler = new HttpHandler(RPC);
  if (process.env.CSPR_CLOUD_API_KEY) {
    handler.setCustomHeaders({ Authorization: process.env.CSPR_CLOUD_API_KEY });
  }
  const client = new RpcClient(handler);
  const result = await client.putDeploy(deploy);
  const txHash = typeof result === 'string' ? result : (result?.deployHash ?? JSON.stringify(result));

  process.stdout.write(JSON.stringify({ success: true, hash: txHash }) + '\n');
}

main().catch((e) => fail(e?.message || String(e)));
