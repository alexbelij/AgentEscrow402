/**
 * id_registry_call.mjs — Submit no-purse-needed agent-identity-registry
 * entry points via plain ContractCallBuilder: update_capabilities,
 * apply_decay, request_deregister, withdraw_stake, slash,
 * configure_min_stake.
 *
 * Env:
 *   CONTRACT_HASH   — 64-hex agent-identity-registry contract hash
 *   ENTRY_POINT     — one of the above
 *   ARGS_JSON       — JSON object mapping arg name -> value. Supported
 *                     value shapes: {"type":"string","value":"..."},
 *                     {"type":"u64","value":123}, {"type":"list_string","value":["a","b"]}
 *   PEM_PATH, KEY_ALGO, CASPER_RPC, CSPR_CLOUD_API_KEY
 */
import fs from 'fs';
import sdk from 'casper-js-sdk';

const { PrivateKey, KeyAlgorithm, ContractCallBuilder, RpcClient, HttpHandler, Args, CLValue } = sdk;
const CLTypeString = sdk.default ? sdk.default.CLTypeString : sdk.CLTypeString;

const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const CONTRACT_HASH = process.env.CONTRACT_HASH;
const ENTRY_POINT = process.env.ENTRY_POINT;
const ARGS_JSON = process.env.ARGS_JSON || '{}';
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = process.env.KEY_ALGO || 'secp256k1';

const VALID = ['update_capabilities', 'apply_decay', 'request_deregister', 'withdraw_stake', 'slash', 'configure_min_stake'];

function fail(msg) {
  process.stdout.write(JSON.stringify({ success: false, error: msg }) + '\n');
  process.exit(1);
}

function buildCLValue(spec) {
  if (spec.type === 'string') return CLValue.newCLString(spec.value);
  if (spec.type === 'u64') return CLValue.newCLUint64(spec.value);
  if (spec.type === 'list_string') return CLValue.newCLList(CLTypeString, spec.value.map(v => CLValue.newCLString(v)));
  throw new Error(`Unsupported arg type: ${spec.type}`);
}

async function main() {
  if (!CONTRACT_HASH || CONTRACT_HASH.length !== 64) fail('CONTRACT_HASH missing or invalid');
  if (!VALID.includes(ENTRY_POINT)) fail(`ENTRY_POINT must be one of: ${VALID.join(', ')}`);
  if (!PEM_PATH) fail('PEM_PATH missing');
  if (!fs.existsSync(PEM_PATH)) fail(`PEM file not found: ${PEM_PATH}`);

  let argsSpec;
  try {
    argsSpec = JSON.parse(ARGS_JSON);
  } catch {
    fail('ARGS_JSON must be valid JSON');
  }

  const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  const sk = await PrivateKey.fromPem(fs.readFileSync(PEM_PATH, 'utf8'), algo);

  const argsMap = {};
  for (const [k, spec] of Object.entries(argsSpec)) {
    argsMap[k] = buildCLValue(spec);
  }
  const args = Args.fromMap(argsMap);

  const tx = new ContractCallBuilder()
    .from(sk.publicKey)
    .byHash(CONTRACT_HASH)
    .entryPoint(ENTRY_POINT)
    .runtimeArgs(args)
    .chainName('casper-test')
    .payment(8_000_000_000) // 8 CSPR — plain state-mutation call
    .build();

  await tx.sign(sk);
  const handler = new HttpHandler(RPC);
  if (process.env.CSPR_CLOUD_API_KEY) {
    handler.setCustomHeaders({ Authorization: process.env.CSPR_CLOUD_API_KEY });
  }
  const client = new RpcClient(handler);
  const res = await client.putTransaction(tx);
  const hash = res.transactionHash?.toHex?.() || JSON.stringify(res.transactionHash);

  process.stdout.write(JSON.stringify({ success: true, hash }) + '\n');
}

main().catch(err => fail(err?.message || String(err)));
