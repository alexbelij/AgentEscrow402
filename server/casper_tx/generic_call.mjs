/**
 * generic_call.mjs — Submit a stored-contract entry-point call with
 * arbitrary args to any contract hash, no purse involved.
 *
 * Env:
 *   CONTRACT_HASH   — 64-hex contract hash
 *   ENTRY_POINT     — entry point name
 *   ARGS_JSON       — JSON object mapping arg name -> {"type":..., "value":...}
 *                     Supported types: string, u64, u256, key_account (hex account hash)
 *   PAYMENT_MOTES   — default 20 CSPR
 *   PEM_PATH, KEY_ALGO, CASPER_RPC, CSPR_CLOUD_API_KEY
 */
import fs from 'fs';
import sdk from 'casper-js-sdk';

const { PrivateKey, KeyAlgorithm, ContractCallBuilder, RpcClient, HttpHandler, CLValue, Key, Args } = sdk;
const CLTypeString = sdk.default ? sdk.default.CLTypeString : sdk.CLTypeString;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const CONTRACT_HASH = process.env.CONTRACT_HASH;
const ENTRY_POINT = process.env.ENTRY_POINT;
const ARGS_JSON = process.env.ARGS_JSON || '{}';
const PAYMENT = process.env.PAYMENT_MOTES || '20000000000';
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = process.env.KEY_ALGO || 'secp256k1';

function fail(msg) {
  process.stdout.write(JSON.stringify({ success: false, error: msg }) + '\n');
  process.exit(1);
}

function buildCLValue(spec) {
  if (spec.type === 'string') return CLValue.newCLString(spec.value);
  if (spec.type === 'u64') return CLValue.newCLUint64(spec.value);
  if (spec.type === 'u256') return CLValue.newCLUInt256(spec.value);
  if (spec.type === 'key_account') {
    return CLValue.newCLKey(Key.newKey('account-hash-' + spec.value));
  }
  if (spec.type === 'key_hash') {
    return CLValue.newCLKey(Key.newKey('hash-' + spec.value));
  }
  if (spec.type === 'list_string') {
    return CLValue.newCLList(CLTypeString, (spec.value || []).map((s) => CLValue.newCLString(s)));
  }
  throw new Error(`Unsupported arg type: ${spec.type}`);
}

async function main() {
  if (!CONTRACT_HASH || CONTRACT_HASH.length !== 64) fail('CONTRACT_HASH missing or invalid');
  if (!ENTRY_POINT) fail('ENTRY_POINT missing');
  if (!PEM_PATH) fail('PEM_PATH missing');

  let argsSpec;
  try { argsSpec = JSON.parse(ARGS_JSON); } catch { fail('ARGS_JSON must be valid JSON'); }

  const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  const sk = await PrivateKey.fromPem(fs.readFileSync(PEM_PATH, 'utf8'), algo);

  const argsMap = {};
  for (const [k, spec] of Object.entries(argsSpec)) argsMap[k] = buildCLValue(spec);

  const builder = new ContractCallBuilder()
    .byHash(CONTRACT_HASH)
    .entryPoint(ENTRY_POINT)
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
main().catch(e => fail(process.env.DEBUG ? (e.stack || String(e)) : (e.message || String(e))));
