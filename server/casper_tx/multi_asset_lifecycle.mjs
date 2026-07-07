/**
 * multi_asset_lifecycle.mjs — Submit MultiAssetEscrow / test-token calls
 * needed to exercise the real on-chain lifecycle (approve, create_escrow,
 * release, refund, dispute, resolve) for docs/evidence.
 *
 * Env:
 *   ACTION          — approve | create_escrow | release | refund | dispute | resolve | balance_of
 *   TOKEN_HASH      — test-token contract hash (64 hex)
 *   ESCROW_HASH     — multi-asset-escrow contract hash (64 hex)
 *   ESCROW_PACKAGE_HASH_HEX — multi-asset-escrow package hash (64 hex, for approve's spender)
 *   RECEIVER_HEX / SENDER_HEX — 64-hex account hash args as needed
 *   AMOUNT          — token amount (smallest unit)
 *   SERVICE_HASH    — 64-hex service identifier
 *   TTL             — seconds
 *   FEE_BPS         — basis points
 *   IN_FAVOR_OF     — "sender" | "receiver" (resolve only)
 *   ARBITER_PUBKEYS_JSON / ARBITER_SIGNATURES_JSON — JSON arrays (release/resolve)
 *   PEM_PATH, KEY_ALGO, CASPER_RPC, CSPR_CLOUD_API_KEY, PAYMENT_MOTES
 */
import fs from 'fs';
import sdk from 'casper-js-sdk';

const { PrivateKey, KeyAlgorithm, ContractCallBuilder, RpcClient, HttpHandler, CLValue, Key, Args } = sdk;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.cspr.cloud/rpc';
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = process.env.KEY_ALGO || 'secp256k1';
const PAYMENT = process.env.PAYMENT_MOTES || '30000000000';

function fail(msg) {
  process.stdout.write(JSON.stringify({ success: false, error: msg }) + '\n');
  process.exit(1);
}

function accountArg(hex) {
  return CLValue.newCLByteArray(Buffer.from(hex, 'hex'));
}

async function submit(contractHash, entryPoint, argsMap) {
  const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  const sk = await PrivateKey.fromPem(fs.readFileSync(PEM_PATH, 'utf8'), algo);

  const builder = new ContractCallBuilder()
    .byHash(contractHash)
    .entryPoint(entryPoint)
    .runtimeArgs(Args.fromMap(argsMap))
    .payment(Number(PAYMENT))
    .chainName('casper-test')
    .from(sk.publicKey);

  const deploy = builder.build();
  await deploy.sign(sk);

  const handler = new HttpHandler(RPC);
  if (process.env.CSPR_CLOUD_API_KEY) handler.setCustomHeaders({ Authorization: process.env.CSPR_CLOUD_API_KEY });
  const client = new RpcClient(handler);
  const res = await client.putTransaction(deploy);
  process.stdout.write(JSON.stringify({ success: true, hash: res.transactionHash }) + '\n');
}

async function main() {
  const ACTION = process.env.ACTION;
  if (!PEM_PATH) fail('PEM_PATH missing');

  if (ACTION === 'approve') {
    const TOKEN_HASH = process.env.TOKEN_HASH;
    const spenderKey = CLValue.newCLKey(Key.newKey('hash-' + process.env.ESCROW_PACKAGE_HASH_HEX));
    await submit(TOKEN_HASH, 'approve', {
      spender: spenderKey,
      amount: CLValue.newCLUInt256(process.env.AMOUNT),
    });
  } else if (ACTION === 'create_escrow') {
    const ESCROW_HASH = process.env.ESCROW_HASH;
    await submit(ESCROW_HASH, 'create_escrow', {
      receiver: accountArg(process.env.RECEIVER_HEX),
      amount: CLValue.newCLUInt256(process.env.AMOUNT),
      service_hash: CLValue.newCLString(process.env.SERVICE_HASH),
      ttl: CLValue.newCLUint64(process.env.TTL),
      token_contract_hash: CLValue.newCLString(process.env.TOKEN_HASH),
      fee_bps: CLValue.newCLUint64(process.env.FEE_BPS || '0'),
    });
  } else if (ACTION === 'release') {
    const ESCROW_HASH = process.env.ESCROW_HASH;
    const CLTypeStringL = sdk.default ? sdk.default.CLTypeString : sdk.CLTypeString;
    const pubkeys = JSON.parse(process.env.ARBITER_PUBKEYS_JSON || '[]').map((s) => CLValue.newCLString(s));
    const sigs = JSON.parse(process.env.ARBITER_SIGNATURES_JSON || '[]').map((s) => CLValue.newCLString(s));
    await submit(ESCROW_HASH, 'release', {
      service_hash: CLValue.newCLString(process.env.SERVICE_HASH),
      arbiter_pubkeys: CLValue.newCLList(CLTypeStringL, pubkeys),
      arbiter_signatures: CLValue.newCLList(CLTypeStringL, sigs),
    });
  } else if (ACTION === 'refund') {
    const ESCROW_HASH = process.env.ESCROW_HASH;
    await submit(ESCROW_HASH, 'refund', { service_hash: CLValue.newCLString(process.env.SERVICE_HASH) });
  } else if (ACTION === 'dispute') {
    const ESCROW_HASH = process.env.ESCROW_HASH;
    await submit(ESCROW_HASH, 'dispute', { service_hash: CLValue.newCLString(process.env.SERVICE_HASH) });
  } else if (ACTION === 'resolve') {
    const ESCROW_HASH = process.env.ESCROW_HASH;
    const CLTypeStringL = sdk.default ? sdk.default.CLTypeString : sdk.CLTypeString;
    const pubkeys = JSON.parse(process.env.ARBITER_PUBKEYS_JSON || '[]').map((s) => CLValue.newCLString(s));
    const sigs = JSON.parse(process.env.ARBITER_SIGNATURES_JSON || '[]').map((s) => CLValue.newCLString(s));
    await submit(ESCROW_HASH, 'resolve', {
      service_hash: CLValue.newCLString(process.env.SERVICE_HASH),
      in_favor_of: CLValue.newCLString(process.env.IN_FAVOR_OF),
      arbiter_pubkeys: CLValue.newCLList(CLTypeStringL, pubkeys),
      arbiter_signatures: CLValue.newCLList(CLTypeStringL, sigs),
    });
  } else {
    fail('Unknown ACTION: ' + ACTION);
  }
}

main().catch((e) => fail(process.env.DEBUG ? e.stack || String(e) : e.message || String(e)));
