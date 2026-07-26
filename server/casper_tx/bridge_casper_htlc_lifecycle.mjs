/**
 * bridge_casper_htlc_lifecycle.mjs — Real Casper HTLC lifecycle driver.
 *
 * Called by server/bridge_casper_adapter.py as a subprocess. All secrets
 * flow through env vars (PEM_PATH points at a file on disk read here;
 * never on the command line). Emits one line of progress log +
 * one line of JSON result on stdout.
 *
 * Actions (ACTION env var):
 *   - lock       — submit HTLC.lock(hashlock, timelock, receiver, source_purse, amount)
 *   - claim      — submit HTLC.claim(hashlock, preimage)
 *   - refund     — submit HTLC.refund(hashlock)
 *   - get_status — read-only lookup of the htlc_locks dictionary
 *
 * Env (mutation actions):
 *   PEM_PATH               — deployer key PEM file
 *   KEY_ALGO               — "secp256k1" | "ed25519" (default secp256k1)
 *   CASPER_RPC             — RPC URL
 *   CSPR_CLOUD_API_KEY     — optional Authorization header
 *   CONTRACT_HASH          — HTLC contract hash (with or without hash- prefix)
 *   PAYMENT_MOTES          — payment for the deploy (default 10 CSPR)
 *   WAIT_FOR_INCLUSION     — "1" to poll the deploy until executed
 *
 * Env (per action):
 *   lock:     HASHLOCK_HEX, TIMELOCK_MS, RECEIVER_HEX, AMOUNT_MOTES
 *   claim:    HASHLOCK_HEX, PREIMAGE_HEX
 *   refund:   HASHLOCK_HEX
 *   get_status: HASHLOCK_HEX (no PEM/PAYMENT needed)
 *
 * Emits (single JSON line, last stdout line — everything else is progress):
 *   { success, hash?, status?, block_hash?, error_message?, cost? }
 */
import fs from 'fs';
import crypto from 'crypto';
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
const PEM_PATH = process.env.PEM_PATH;
const KEY_ALGO = (process.env.KEY_ALGO || 'secp256k1').toLowerCase();
const ACTION = process.env.ACTION;
const PAYMENT = process.env.PAYMENT_MOTES || '10000000000';
const CONTRACT_HASH = normalizeHash(process.env.CONTRACT_HASH || '');
const CHAIN_NAME = 'casper-test';
const TTL_MS = 1800000;

function normalizeHash(h) {
  if (!h) return '';
  return h.replace(/^(hash-|contract-|entity-contract-)/, '').toLowerCase();
}

function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + '\n');
}
function progress(msg) {
  process.stdout.write(JSON.stringify({ progress: msg }) + '\n');
}
function fail(msg) {
  emit({ success: false, error: msg });
  process.exit(1);
}

function rpcClient() {
  const handler = new HttpHandler(RPC);
  if (process.env.CSPR_CLOUD_API_KEY) {
    handler.setCustomHeaders({ Authorization: process.env.CSPR_CLOUD_API_KEY });
  }
  return new RpcClient(handler);
}

async function loadKey() {
  if (!PEM_PATH) fail('PEM_PATH required');
  const algo = KEY_ALGO === 'ed25519' ? KeyAlgorithm.ED25519 : KeyAlgorithm.SECP256K1;
  const pem = fs.readFileSync(PEM_PATH, 'utf8');
  return PrivateKey.fromPem(pem, algo);
}

function makeHeader(sk) {
  const h = DeployHeader.default();
  h.account = sk.publicKey;
  h.chainName = CHAIN_NAME;
  h.ttl = new Duration(TTL_MS);
  h.gasPrice = 1;
  return h;
}

async function accountMainPurse(sk) {
  // For Casper 2.0, we can get the caller's main purse via state_get_entity.
  const client = rpcClient();
  const res = await fetch(RPC, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(process.env.CSPR_CLOUD_API_KEY ? { authorization: process.env.CSPR_CLOUD_API_KEY } : {}),
    },
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: 1,
      method: 'state_get_entity',
      params: { entity_identifier: { PublicKey: sk.publicKey.toHex() } },
    }),
  });
  const j = await res.json();
  if (j.error) fail(`state_get_entity: ${j.error.message}`);
  const ent = j.result?.entity || {};
  const purse =
    ent.AddressableEntity?.main_purse ||
    ent.Account?.main_purse ||
    ent.entity?.main_purse;
  if (!purse) {
    // Fallback: Casper 2.0 pre-migration accounts return the Account wrapper
    // WITHOUT a main_purse field — we must fetch it via state_get_account_info
    // for compat with unmigrated 1.x-style accounts on this network.
    const alt = await fetch(RPC, {
      method: 'POST',
      headers: { 'content-type': 'application/json', ...(process.env.CSPR_CLOUD_API_KEY ? { authorization: process.env.CSPR_CLOUD_API_KEY } : {}) },
      body: JSON.stringify({
        jsonrpc: '2.0', id: 1,
        method: 'state_get_account_info',
        params: { public_key: sk.publicKey.toHex() },
      }),
    });
    const alt_j = await alt.json();
    const p2 = alt_j.result?.account?.main_purse;
    if (p2) return p2;
    fail(`no main_purse for ${sk.publicKey.toHex()}`);
  }
  return purse;
}

async function pollDeploy(hashHex) {
  const client = rpcClient();
  const deadline = Date.now() + 120000; // 2 min
  while (Date.now() < deadline) {
    const res = await fetch(RPC, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        ...(process.env.CSPR_CLOUD_API_KEY ? { authorization: process.env.CSPR_CLOUD_API_KEY } : {}),
      },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 1,
        method: 'info_get_deploy',
        params: [hashHex],
      }),
    });
    const j = await res.json();
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
    await new Promise((r) => setTimeout(r, 3000));
  }
  return { status: 'pending', block_hash: null, error_message: 'timeout waiting for inclusion', cost: null };
}

// ── ACTIONS ─────────────────────────────────────────────────────────

async function actionLock() {
  const HASHLOCK = process.env.HASHLOCK_HEX;
  const TIMELOCK = BigInt(process.env.TIMELOCK_MS || '0');
  const RECEIVER = (process.env.RECEIVER_HEX || '').replace(/^account-hash-/, '');
  const AMOUNT = process.env.AMOUNT_MOTES;

  if (!HASHLOCK || HASHLOCK.length !== 64) fail('HASHLOCK_HEX must be 64 hex chars');
  if (!RECEIVER || RECEIVER.length !== 64) fail('RECEIVER_HEX must be 64 hex chars (account-hash bytes)');
  if (!AMOUNT || BigInt(AMOUNT) <= 0n) fail('AMOUNT_MOTES must be > 0');
  if (!CONTRACT_HASH) fail('CONTRACT_HASH required');

  const sk = await loadKey();
  const purse = await accountMainPurse(sk);
  progress(`resolved main_purse=${purse}`);

  const args = Args.fromMap({
    hashlock_hex: CLValue.newCLString(HASHLOCK),
    timelock_ms: CLValue.newCLUint64(TIMELOCK),
    receiver: CLValue.newCLByteArray(new Uint8Array(Buffer.from(RECEIVER, 'hex'))),
    source_purse: CLValue.newCLUref(purseFromString(purse)),
    amount: CLValue.newCLUInt512(BigInt(AMOUNT)),
  });

  const session = ExecutableDeployItem.newStoredContractByHash(
    fromHexHash(CONTRACT_HASH),
    'lock',
    args,
  );
  const payment = ExecutableDeployItem.standardPayment(PAYMENT);
  const deploy = Deploy.makeDeploy(makeHeader(sk), payment, session);
  await deploy.sign(sk);

  const client = rpcClient();
  const putRes = await client.putDeploy(deploy);
  const hash = typeof putRes === 'string' ? putRes : putRes?.deployHash ?? '';
  progress(`submitted deploy=${hash}`);

  const wait = process.env.WAIT_FOR_INCLUSION === '1';
  if (wait) {
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

  const sk = await loadKey();

  const args = Args.fromMap({
    hashlock_hex: CLValue.newCLString(HASHLOCK),
    preimage: CLValue.newCLList(sdk.CLTypeUInt8, Array.from(Buffer.from(PREIMAGE, 'hex')).map(b => CLValue.newCLUint8(b))),
  });

  const session = ExecutableDeployItem.newStoredContractByHash(
    fromHexHash(CONTRACT_HASH),
    'claim',
    args,
  );
  const payment = ExecutableDeployItem.standardPayment(PAYMENT);
  const deploy = Deploy.makeDeploy(makeHeader(sk), payment, session);
  await deploy.sign(sk);

  const client = rpcClient();
  const putRes = await client.putDeploy(deploy);
  const hash = typeof putRes === 'string' ? putRes : putRes?.deployHash ?? '';
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

  const sk = await loadKey();

  const args = Args.fromMap({
    hashlock_hex: CLValue.newCLString(HASHLOCK),
  });

  const session = ExecutableDeployItem.newStoredContractByHash(
    fromHexHash(CONTRACT_HASH),
    'refund',
    args,
  );
  const payment = ExecutableDeployItem.standardPayment(PAYMENT);
  const deploy = Deploy.makeDeploy(makeHeader(sk), payment, session);
  await deploy.sign(sk);

  const client = rpcClient();
  const putRes = await client.putDeploy(deploy);
  const hash = typeof putRes === 'string' ? putRes : putRes?.deployHash ?? '';
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

  // Query the contract's named_keys → find htlc_locks dictionary uref →
  // query_global_state at that uref with HASHLOCK as the dict key.
  const auth = process.env.CSPR_CLOUD_API_KEY ? { authorization: process.env.CSPR_CLOUD_API_KEY } : {};

  const entRes = await fetch(RPC, {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...auth },
    body: JSON.stringify({
      jsonrpc: '2.0', id: 1,
      method: 'state_get_entity',
      params: { entity_identifier: { ContractHash: `contract-${CONTRACT_HASH}` } },
    }),
  });
  const ent = await entRes.json();
  if (ent.error) fail(`state_get_entity: ${ent.error.message}`);

  // Casper 2.0 contract query doesn't expose dict urefs via state_get_entity
  // directly (dicts are created lazily inside entry points). Instead, we
  // must resolve htlc_locks via state_get_dictionary_item using the
  // ContractNamedKey identifier — which knows how to walk the contract's
  // named-keys internally.
  // First fetch a state_root_hash — some RPC endpoints require it.
  const srhRes = await fetch(RPC, {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...auth },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'chain_get_state_root_hash', params: [] }),
  });
  const srh = (await srhRes.json()).result?.state_root_hash;
  if (!srh) fail('cannot fetch state_root_hash');

  const dictRes = await fetch(RPC, {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...auth },
    body: JSON.stringify({
      jsonrpc: '2.0', id: 1,
      method: 'state_get_dictionary_item',
      params: {
        state_root_hash: srh,
        dictionary_identifier: {
          ContractNamedKey: {
            key: `hash-${CONTRACT_HASH}`,
            dictionary_name: 'htlc_locks',
            dictionary_item_key: HASHLOCK,
          },
        },
      },
    }),
  });
  const dict = await dictRes.json();
  if (dict.error) {
    // "ValueNotFound" simply means the dictionary hasn't been created yet
    // (no lock has ever occurred on this deployment) or the specific key
    // isn't present — both map to EMPTY state.
    const msg = String(dict.error.message || '').toLowerCase();
    // "Node request failure" without further detail is what casper-node emits
    // when the requested dictionary doesn't exist yet on this contract (no
    // lock has ever been submitted, so htlc_locks named key + dict weren't
    // materialised). Same logical outcome as ValueNotFound => EMPTY.
    if (
      msg.includes('valuenotfound') ||
      msg.includes('not found') ||
      msg.includes('failed to find') ||
      msg.includes('node request failure') ||
      msg.includes('failed to lookup')
    ) {
      emit({ success: true, hash: '', status: 'success', error_message: JSON.stringify({ status: 'EMPTY', amount: 0, record: null }) });
      return;
    }
    fail(`state_get_dictionary_item: ${dict.error.message}`);
  }

  // Parse the CLValue-encoded SwapRecord. Layout (from main.rs):
  //   ((sender_hex, receiver_hex, amount_str), (state, timelock_ms))
  // The RPC parsed representation gives us the tuple structure directly.
  const parsed = dict.result?.stored_value?.CLValue?.parsed;
  if (!parsed) {
    emit({ success: true, hash: '', status: 'success', error_message: JSON.stringify({ status: 'EMPTY', amount: 0, record: null }) });
    return;
  }
  // parsed is an array [[sender_hex, receiver_hex, amount_str], [state_num, timelock_ms]]
  const [meta, sm] = parsed;
  const [sender_hex, receiver_hex, amount_str] = meta;
  const [state_num, timelock_ms] = sm;
  const STATE_NAMES = { 0: 'EMPTY', 1: 'LOCKED', 2: 'CLAIMED', 3: 'REFUNDED' };
  const statusName = STATE_NAMES[state_num] || `UNKNOWN(${state_num})`;
  const remaining = statusName === 'LOCKED' ? amount_str : '0';
  emit({
    success: true,
    hash: '',
    status: 'success',
    error_message: JSON.stringify({
      status: statusName,
      amount: remaining,
      record: {
        sender: sender_hex,
        receiver: receiver_hex,
        amount: amount_str,
        state: state_num,
        timelock_ms,
      },
    }),
  });
}

// ── Hash / URef helpers ─────────────────────────────────────────────

function fromHexHash(hex) {
  return new Uint8Array(Buffer.from(hex, 'hex'));
}

function purseFromString(s) {
  // s looks like "uref-abcd...-007" — strip the prefix, parse address + access bits.
  const m = /^uref-([0-9a-f]{64})-(\d+)$/i.exec(s);
  if (!m) fail(`bad uref: ${s}`);
  const addr = new Uint8Array(Buffer.from(m[1], 'hex'));
  const accessBits = parseInt(m[2], 10);
  // casper-js-sdk exposes URef via CLTypeUref & the `URef` class; the
  // easiest working path is to build a raw CLValue via the string form.
  return sdk.URef.fromString(s);
}

// ── Dispatch ────────────────────────────────────────────────────────

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
