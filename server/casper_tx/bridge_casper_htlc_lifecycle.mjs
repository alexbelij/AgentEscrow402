/**
 * bridge_casper_htlc_lifecycle.mjs — Real Casper HTLC lifecycle driver.
 *
 * Node-side subprocess for server/bridge_casper_adapter.py. All secrets flow
 * through env vars (PEM_PATH points at a file read here; never on CLI args).
 * Emits progress lines + final JSON result on stdout.
 *
 * Uses casper-js-sdk 5.x ContractCallBuilder — Casper 2.0 modern transaction
 * format (not legacy Deploy). Matches the pattern used by the working
 * escrow-manager scripts in this same directory.
 *
 * Actions (ACTION env var):
 *   lock       — HTLC.lock(hashlock_hex, timelock_ms, receiver, source_purse, amount)
 *   claim      — HTLC.claim(hashlock_hex, preimage)
 *   refund     — HTLC.refund(hashlock_hex)
 *   get_status — read-only lookup of htlc_locks dictionary
 *
 * Env — mutation actions:
 *   PEM_PATH, KEY_ALGO, CASPER_RPC, CSPR_CLOUD_API_KEY,
 *   CONTRACT_HASH (with or w/o hash- prefix), PAYMENT_MOTES, WAIT_FOR_INCLUSION
 *
 * Env — per-action:
 *   lock:       HASHLOCK_HEX, TIMELOCK_MS, RECEIVER_HEX, AMOUNT_MOTES
 *   claim:      HASHLOCK_HEX, PREIMAGE_HEX
 *   refund:     HASHLOCK_HEX
 *   get_status: HASHLOCK_HEX
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import sdk from 'casper-js-sdk';

const {
  PrivateKey, KeyAlgorithm,
  RpcClient, HttpHandler,
  ContractCallBuilder, SessionBuilder,
  Args, CLValue, URef, CLTypeString, CLTypeUInt8,
} = sdk;

const __dir = path.dirname(fileURLToPath(import.meta.url));
const HTLC_FUNDER_WASM = process.env.HTLC_FUNDER_WASM || path.join(__dir, 'htlc_funder.wasm');

const RPC = process.env.CASPER_RPC || 'https://node.testnet.casper.network/rpc';
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = (process.env.KEY_ALGO || 'secp256k1').toLowerCase();
const ACTION = process.env.ACTION;
const CONTRACT_HASH = normalizeHash(process.env.CONTRACT_HASH || '');
const CHAIN_NAME = 'casper-test';
const PAYMENT = BigInt(process.env.PAYMENT_MOTES || '10000000000');

function normalizeHash(h) {
  if (!h) return '';
  return h.replace(/^(hash-|contract-|entity-contract-)/, '').toLowerCase();
}
function emit(obj) { process.stdout.write(JSON.stringify(obj) + '\n'); }
function progress(msg) { process.stdout.write(JSON.stringify({ progress: msg }) + '\n'); }
function fail(msg) { emit({ success: false, error: msg }); process.exit(1); }

function rpcHeaders() {
  return process.env.CSPR_CLOUD_API_KEY ? { authorization: process.env.CSPR_CLOUD_API_KEY } : {};
}
async function rpcCall(method, params) {
  const res = await fetch(RPC, {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...rpcHeaders() },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }),
  });
  return await res.json();
}
function loadKey() {
  if (!PEM_PATH) fail('PEM_PATH required');
  const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  return PrivateKey.fromPem(fs.readFileSync(PEM_PATH, 'utf8'), algo);
}
function rpcClient() {
  const h = new HttpHandler(RPC);
  if (process.env.CSPR_CLOUD_API_KEY) h.setCustomHeaders({ Authorization: process.env.CSPR_CLOUD_API_KEY });
  return new RpcClient(h);
}

async function mainPurseForAccount(pubkeyHex) {
  // Prefer state_get_entity, fall back to state_get_account_info for
  // unmigrated 1.x-style accounts on this network.
  const ent = await rpcCall('state_get_entity', { entity_identifier: { PublicKey: pubkeyHex } });
  const e = ent.result?.entity || {};
  const purse =
    e.AddressableEntity?.main_purse ||
    e.Account?.main_purse ||
    e.entity?.main_purse;
  if (purse) return purse;
  const acc = await rpcCall('state_get_account_info', { public_key: pubkeyHex });
  const p2 = acc.result?.account?.main_purse;
  if (p2) return p2;
  fail(`no main_purse for ${pubkeyHex}`);
}

async function pollDeploy(hashHex) {
  const deadline = Date.now() + 180000;
  while (Date.now() < deadline) {
    // Casper 2.0 modern txs land in info_get_transaction, but the SDK
    // ContractCallBuilder.buildFor1_5() route uses the legacy Deploy path
    // and we lookup via info_get_deploy.
    const j = await rpcCall('info_get_deploy', [hashHex]);
    if (!j.error) {
      const exec = j.result?.execution_info?.execution_result?.Version2;
      const block = j.result?.execution_info?.block_hash;
      if (exec) {
        return {
          status: exec.error_message ? 'failure' : 'success',
          block_hash: block,
          error_message: exec.error_message || null,
          cost: exec.limit,
        };
      }
    }
    await new Promise(r => setTimeout(r, 3000));
  }
  return { status: 'pending', block_hash: null, error_message: 'timeout', cost: null };
}

async function buildAndSend(sk, args, entryPoint) {
  const tx = new ContractCallBuilder()
    .from(sk.publicKey)
    .byHash(CONTRACT_HASH)
    .entryPoint(entryPoint)
    .runtimeArgs(args)
    .chainName(CHAIN_NAME)
    .payment(Number(PAYMENT))
    .buildFor1_5();
  await tx.sign(sk);
  const client = rpcClient();
  const res = await client.putTransaction(tx);
  const hash = res.transactionHash?.toHex?.() || res.deployHash || (typeof res === 'string' ? res : '');
  return hash;
}

// ── Actions ─────────────────────────────────────────────────────────

async function actionLock() {
  const HASHLOCK = process.env.HASHLOCK_HEX;
  const TIMELOCK = BigInt(process.env.TIMELOCK_MS || '0');
  const RECEIVER = (process.env.RECEIVER_HEX || '').replace(/^account-hash-/, '');
  const AMOUNT = process.env.AMOUNT_MOTES;

  if (!HASHLOCK || HASHLOCK.length !== 64) fail('HASHLOCK_HEX must be 64 hex chars');
  if (!RECEIVER || RECEIVER.length !== 64) fail('RECEIVER_HEX must be 64 hex chars (account-hash bytes)');
  if (!AMOUNT || BigInt(AMOUNT) <= 0n) fail('AMOUNT_MOTES must be > 0');
  if (!CONTRACT_HASH) fail('CONTRACT_HASH required');
  if (!fs.existsSync(HTLC_FUNDER_WASM)) fail(`funder wasm not found: ${HTLC_FUNDER_WASM}`);

  const sk = loadKey();

  // Casper 2.0 gotcha: a purse URef passed as a *deploy* runtime arg over RPC
  // has its access rights stripped ("Mint error: 4" InvalidAccessRights on any
  // contract-side transfer). Instead, run a small session-wasm (htlc-funder)
  // that creates a fresh purse in session context, funds it from main_purse,
  // and forwards it via a native call_contract into casper-htlc.lock().
  // Also: Casper 2.0 requires a top-level session arg literally named
  // `amount` for the Mint spending limit — pass it here too.
  const wasm = new Uint8Array(fs.readFileSync(HTLC_FUNDER_WASM));
  const args = Args.fromMap({
    amount: CLValue.newCLUInt512(BigInt(AMOUNT)),
    contract_hash: CLValue.newCLString(CONTRACT_HASH),
    hashlock_hex: CLValue.newCLString(HASHLOCK),
    timelock_ms: CLValue.newCLUint64(TIMELOCK),
    receiver: CLValue.newCLString(RECEIVER),
  });

  const tx = new SessionBuilder()
    .from(sk.publicKey)
    .wasm(wasm)
    .runtimeArgs(args)
    .chainName(CHAIN_NAME)
    .payment(Number(PAYMENT))
    .build();
  await tx.sign(sk);
  const client = rpcClient();
  const res = await client.putTransaction(tx);
  const hash = res.transactionHash?.toHex?.() || res.deployHash || (typeof res === 'string' ? res : '');
  progress(`submitted deploy=${hash}`);
  if (process.env.WAIT_FOR_INCLUSION === '1') {
    const info = await pollDeploy(hash);
    emit({ success: info.status === 'success', hash, ...info });
  } else {
    emit({ success: true, hash, status: 'pending' });
  }
}

async function actionClaim() {
  const HASHLOCK = process.env.HASHLOCK_HEX;
  const PREIMAGE = process.env.PREIMAGE_HEX;
  if (!HASHLOCK || HASHLOCK.length !== 64) fail('HASHLOCK_HEX must be 64 hex chars');
  if (!PREIMAGE) fail('PREIMAGE_HEX required');
  if (!CONTRACT_HASH) fail('CONTRACT_HASH required');
  const sk = loadKey();
  const preimageBytes = new Uint8Array(Buffer.from(PREIMAGE, 'hex'));
  const args = Args.fromMap({
    hashlock_hex: CLValue.newCLString(HASHLOCK),
    preimage: CLValue.newCLList(CLTypeUInt8, Array.from(preimageBytes, b => CLValue.newCLUint8(b))),
  });
  const hash = await buildAndSend(sk, args, 'claim');
  progress(`submitted deploy=${hash}`);
  if (process.env.WAIT_FOR_INCLUSION === '1') {
    const info = await pollDeploy(hash);
    emit({ success: info.status === 'success', hash, ...info });
  } else {
    emit({ success: true, hash, status: 'pending' });
  }
}

async function actionRefund() {
  const HASHLOCK = process.env.HASHLOCK_HEX;
  if (!HASHLOCK || HASHLOCK.length !== 64) fail('HASHLOCK_HEX must be 64 hex chars');
  if (!CONTRACT_HASH) fail('CONTRACT_HASH required');
  const sk = loadKey();
  const args = Args.fromMap({
    hashlock_hex: CLValue.newCLString(HASHLOCK),
  });
  const hash = await buildAndSend(sk, args, 'refund');
  progress(`submitted deploy=${hash}`);
  if (process.env.WAIT_FOR_INCLUSION === '1') {
    const info = await pollDeploy(hash);
    emit({ success: info.status === 'success', hash, ...info });
  } else {
    emit({ success: true, hash, status: 'pending' });
  }
}

async function actionGetStatus() {
  const HASHLOCK = process.env.HASHLOCK_HEX;
  if (!HASHLOCK || HASHLOCK.length !== 64) fail('HASHLOCK_HEX must be 64 hex chars');
  if (!CONTRACT_HASH) fail('CONTRACT_HASH required');

  const srh = (await rpcCall('chain_get_state_root_hash', [])).result?.state_root_hash;
  if (!srh) fail('cannot fetch state_root_hash');

  const dict = await rpcCall('state_get_dictionary_item', {
    state_root_hash: srh,
    dictionary_identifier: {
      ContractNamedKey: {
        key: `hash-${CONTRACT_HASH}`,
        dictionary_name: 'htlc_locks',
        dictionary_item_key: HASHLOCK,
      },
    },
  });
  if (dict.error) {
    const msg = String(dict.error.message || '').toLowerCase();
    if (
      msg.includes('valuenotfound') ||
      msg.includes('not found') ||
      msg.includes('failed to find') ||
      msg.includes('node request failure') ||
      msg.includes('failed to lookup') ||
      msg.includes('query failed')
    ) {
      emit({ success: true, hash: '', status: 'success', error_message: JSON.stringify({ status: 'EMPTY', amount: 0, record: null }) });
      return;
    }
    fail(`state_get_dictionary_item: ${dict.error.message}`);
  }
  const parsed = dict.result?.stored_value?.CLValue?.parsed;
  if (!parsed) {
    emit({ success: true, hash: '', status: 'success', error_message: JSON.stringify({ status: 'EMPTY', amount: 0, record: null }) });
    return;
  }
  const [meta, sm] = parsed;
  const [sender_hex, receiver_hex, amount_str] = meta;
  const [state_num, timelock_ms] = sm;
  const STATE_NAMES = { 0: 'EMPTY', 1: 'LOCKED', 2: 'CLAIMED', 3: 'REFUNDED' };
  const statusName = STATE_NAMES[state_num] || `UNKNOWN(${state_num})`;
  const remaining = statusName === 'LOCKED' ? amount_str : '0';
  emit({
    success: true, hash: '', status: 'success',
    error_message: JSON.stringify({
      status: statusName,
      amount: remaining,
      record: { sender: sender_hex, receiver: receiver_hex, amount: amount_str, state: state_num, timelock_ms },
    }),
  });
}

async function main() {
  try {
    switch (ACTION) {
      case 'lock': return await actionLock();
      case 'claim': return await actionClaim();
      case 'refund': return await actionRefund();
      case 'get_status': return await actionGetStatus();
      default: fail(`unknown ACTION=${ACTION}`);
    }
  } catch (e) {
    fail(e?.message || String(e));
  }
}
main();
