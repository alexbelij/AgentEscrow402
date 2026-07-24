#![no_std]
#![no_main]

//! Range-Proof Registry for AE402 escrow amounts.
//!
//! Casper's WASM host exposes Ed25519 verification but no modular
//! exponentiation over large integers and no elliptic-curve pairings,
//! so a Bulletproofs-style range-proof verifier cannot run on-chain
//! within a realistic gas budget. This contract therefore uses an
//! **arbiter-attested** verification model that keeps the *hiding*
//! property of the commitment on-chain while pushing the heavy proof
//! math off-chain into a deterministic, cross-language verifier
//! (`sdk/range_proof.py`).
//!
//! ## Flow
//!
//! 1. **Register.** A prover publishes:
//!    - a hiding commitment (opaque bytes) — typically
//!      `commitment = g^amount * h^randomness mod p` under a pre-agreed
//!      group,
//!    - the BLAKE2b hash of a full off-chain proof blob,
//!    - the declared inclusive range `[min, max]`,
//!    - the arbiter set (list of Ed25519 public keys) authorised to
//!      attest this specific record, and
//!    - the threshold `t` such that any `t` attestations flip the
//!      record to `Verified`.
//!
//! 2. **Attest.** Each arbiter verifies the off-chain proof
//!    deterministically and, if it passes, submits a domain-separated
//!    Ed25519 signature over
//!    `ae402:range-proof:v1:attest:<pkg>:<escrow_id>:<commitment>:<proof_hash>:<min>:<max>`.
//!    The contract deduplicates attesters, verifies each signature
//!    on-chain, and increments a counter.
//!
//! 3. **Finalize.** Once `attest_count >= threshold`, anyone can call
//!    `finalize()` to flip status Pending → Verified. Downstream
//!    settlement contracts (e.g. escrow.rs) treat status == Verified
//!    as an on-chain assertion that the hidden amount is in
//!    `[min, max]`.
//!
//! 4. **Open.** When the escrow settles, the party may `open()` the
//!    commitment by publishing `(amount, randomness_hash)`. On-chain
//!    we enforce `min <= amount <= max`; off-chain any observer can
//!    then recompute `g^amount * h^randomness == commitment` and
//!    dispute via `mark_fraud` if it disagrees.
//!
//! 5. **Fraud.** Any arbiter may flip the record to `Fraud` from any
//!    non-`Fraud` non-`Unset` status by submitting a signed dispute.
//!    Fraud is terminal for downstream settlement.
//!
//! ## Domain-separated preimages
//!
//! Every signed message embeds this deployment's `self_package_hash`
//! (32-byte contract package hash) so a signature made against one
//! deployed instance cannot be replayed against another. Preimages
//! are byte-for-byte identical to `sdk/range_proof.py::attest_preimage`
//! and `::fraud_preimage`, verified in
//! `contracts/tests/src/range_proof_registry_property_tests.rs`.
//!
//! Full threat model: `docs/RANGE_PROOFS.md`.

extern crate alloc;

use alloc::boxed::Box;
use alloc::string::{String, ToString};
use alloc::vec;
use alloc::vec::Vec;

use casper_contract::contract_api::{runtime, storage};
use casper_contract::unwrap_or_revert::UnwrapOrRevert;
use casper_types::bytesrepr::ToBytes;
use casper_types::contracts::{ContractPackageHash, NamedKeys};
use casper_types::crypto::{self, PublicKey, Signature};
use casper_types::{
    ApiError, AsymmetricType, CLType, CLTyped, CLValue, EntityEntryPoint, EntryPointAccess,
    EntryPointPayment, EntryPointType, EntryPoints, Parameter,
};
use casper_types::bytesrepr::FromBytes;

// ── Error codes ──────────────────────────────────────────────────────

const ERR_UNAUTHORIZED: u16 = 1;
const ERR_INVALID_SIGNATURE: u16 = 2;
const ERR_UNKNOWN_ESCROW: u16 = 3;
const ERR_ALREADY_REGISTERED: u16 = 4;
const ERR_INVALID_RANGE: u16 = 5;
const ERR_ARBITER_NOT_IN_SET: u16 = 6;
const ERR_ARBITER_DUPLICATE_ATTEST: u16 = 7;
const ERR_STATUS_TRANSITION: u16 = 8;
const ERR_INVALID_COMMITMENT: u16 = 9;
const ERR_INVALID_PROOF_HASH: u16 = 10;
const ERR_MISSING_KEY: u16 = 12;
const ERR_THRESHOLD_UNMET: u16 = 13;
const ERR_TOO_MANY_ARBITERS: u16 = 14;
const ERR_AMOUNT_OUT_OF_RANGE: u16 = 16;
const ERR_INVALID_RANDOMNESS_HASH: u16 = 17;
const ERR_HEX_DECODE: u16 = 18;

// ── Domain-separation constants ──────────────────────────────────────

const DOMAIN: &str = "ae402:range-proof:v1";

// ── Named storage keys ───────────────────────────────────────────────

const ADMIN_KEY: &str = "admin";
const SELF_PACKAGE_KEY: &str = "self_package_hash";

const REC_COMMITMENT: &str = "rec_commitment";
const REC_PROOF_HASH: &str = "rec_proof_hash";
const REC_MIN: &str = "rec_min";
const REC_MAX: &str = "rec_max";
const REC_ARBITER_SET_HEX: &str = "rec_arbiter_set_hex"; // Vec<String>
const REC_THRESHOLD: &str = "rec_threshold";
const REC_ATTEST_COUNT: &str = "rec_attest_count";
const REC_ATTESTERS_HEX: &str = "rec_attesters_hex"; // Vec<String>
const REC_STATUS: &str = "rec_status";
const REC_OPENED_AMOUNT: &str = "rec_opened_amount";
const REC_OPENED_RANDOMNESS_HASH: &str = "rec_opened_r_hash";

// ── Status codes ─────────────────────────────────────────────────────

const STATUS_UNSET: u8 = 0;
const STATUS_PENDING: u8 = 1;
const STATUS_VERIFIED: u8 = 2;
const STATUS_OPENED: u8 = 3;
const STATUS_FRAUD: u8 = 4;

// ── Limits ────────────────────────────────────────────────────────────

const MAX_ARBITERS: usize = 32;
const COMMITMENT_MAX_LEN: usize = 512;
const HASH_LEN: usize = 32;

// ══════════════════════════════════════════════════════════════════════
// Helpers
// ══════════════════════════════════════════════════════════════════════

fn read_named<T: FromBytes + CLTyped>(name: &str) -> T {
    let uref = runtime::get_key(name)
        .unwrap_or_revert_with(ApiError::User(ERR_MISSING_KEY))
        .into_uref()
        .unwrap_or_revert_with(ApiError::User(ERR_MISSING_KEY));
    storage::read::<T>(uref)
        .unwrap_or_revert()
        .unwrap_or_revert_with(ApiError::User(ERR_MISSING_KEY))
}

fn dict_get<T: FromBytes + CLTyped>(dict: &str, key: &str) -> Option<T> {
    let uref = runtime::get_key(dict)
        .unwrap_or_revert_with(ApiError::User(ERR_MISSING_KEY))
        .into_uref()
        .unwrap_or_revert_with(ApiError::User(ERR_MISSING_KEY));
    storage::dictionary_get::<T>(uref, key).unwrap_or_revert()
}

fn dict_put<T: ToBytes + CLTyped>(dict: &str, key: &str, value: T) {
    let uref = runtime::get_key(dict)
        .unwrap_or_revert_with(ApiError::User(ERR_MISSING_KEY))
        .into_uref()
        .unwrap_or_revert_with(ApiError::User(ERR_MISSING_KEY));
    storage::dictionary_put(uref, key, value);
}

fn self_package_hex() -> String {
    read_named::<String>(SELF_PACKAGE_KEY)
}

fn escrow_key(escrow_id_hex: &str) -> String {
    escrow_id_hex.to_string()
}

fn hex_lower(bytes: &[u8]) -> String {
    const HEX: &[u8] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        out.push(HEX[(b >> 4) as usize] as char);
        out.push(HEX[(b & 0x0f) as usize] as char);
    }
    out
}

fn hex_decode(hex: &str) -> Vec<u8> {
    if hex.len() % 2 != 0 {
        runtime::revert(ApiError::User(ERR_HEX_DECODE));
    }
    let bytes = hex.as_bytes();
    let mut out = Vec::with_capacity(hex.len() / 2);
    for chunk in bytes.chunks(2) {
        let hi = nibble(chunk[0]);
        let lo = nibble(chunk[1]);
        out.push((hi << 4) | lo);
    }
    out
}

fn nibble(c: u8) -> u8 {
    match c {
        b'0'..=b'9' => c - b'0',
        b'a'..=b'f' => c - b'a' + 10,
        b'A'..=b'F' => c - b'A' + 10,
        _ => runtime::revert(ApiError::User(ERR_HEX_DECODE)),
    }
}

fn record_exists(k: &str) -> bool {
    dict_get::<u8>(REC_STATUS, k)
        .map(|s| s != STATUS_UNSET)
        .unwrap_or(false)
}

fn read_status(k: &str) -> u8 {
    dict_get::<u8>(REC_STATUS, k).unwrap_or(STATUS_UNSET)
}

fn require_status(status: u8, allowed: &[u8]) {
    if !allowed.iter().any(|s| *s == status) {
        runtime::revert(ApiError::User(ERR_STATUS_TRANSITION));
    }
}

fn u64_to_dec(mut n: u64) -> String {
    if n == 0 {
        return String::from("0");
    }
    let mut buf: [u8; 20] = [0; 20];
    let mut i = 0usize;
    while n > 0 {
        buf[i] = b'0' + (n % 10) as u8;
        n /= 10;
        i += 1;
    }
    let mut s = String::with_capacity(i);
    for j in (0..i).rev() {
        s.push(buf[j] as char);
    }
    s
}

// Canonical preimages. MUST match sdk/range_proof.py byte-for-byte.

fn attest_preimage(
    escrow_id_hex: &str,
    commitment_hex: &str,
    proof_hash_hex: &str,
    min_amount: u64,
    max_amount: u64,
) -> String {
    let mut s = String::new();
    s.push_str(DOMAIN);
    s.push_str(":attest:");
    s.push_str(&self_package_hex());
    s.push(':');
    s.push_str(escrow_id_hex);
    s.push(':');
    s.push_str(commitment_hex);
    s.push(':');
    s.push_str(proof_hash_hex);
    s.push(':');
    s.push_str(&u64_to_dec(min_amount));
    s.push(':');
    s.push_str(&u64_to_dec(max_amount));
    s
}

fn fraud_preimage(
    escrow_id_hex: &str,
    commitment_hex: &str,
    proof_hash_hex: &str,
    reason_hash_hex: &str,
) -> String {
    let mut s = String::new();
    s.push_str(DOMAIN);
    s.push_str(":fraud:");
    s.push_str(&self_package_hex());
    s.push(':');
    s.push_str(escrow_id_hex);
    s.push(':');
    s.push_str(commitment_hex);
    s.push(':');
    s.push_str(proof_hash_hex);
    s.push(':');
    s.push_str(reason_hash_hex);
    s
}

fn verify_signature(pubkey_hex: &str, sig_hex: &str, message: &str) {
    let public_key = match PublicKey::from_hex(pubkey_hex.as_bytes()) {
        Ok(k) => k,
        Err(_) => runtime::revert(ApiError::User(ERR_INVALID_SIGNATURE)),
    };
    let signature = match Signature::from_hex(sig_hex.as_bytes()) {
        Ok(s) => s,
        Err(_) => runtime::revert(ApiError::User(ERR_INVALID_SIGNATURE)),
    };
    if crypto::verify(message.as_bytes(), &signature, &public_key).is_err() {
        runtime::revert(ApiError::User(ERR_INVALID_SIGNATURE));
    }
}

fn pk_in_set(pk_hex: &str, set: &[String]) -> bool {
    set.iter().any(|k| k == pk_hex)
}

// ══════════════════════════════════════════════════════════════════════
// Entry points
// ══════════════════════════════════════════════════════════════════════

#[no_mangle]
pub extern "C" fn init() {
    if runtime::has_key(SELF_PACKAGE_KEY) {
        runtime::revert(ApiError::User(ERR_UNAUTHORIZED));
    }
    let admin: String = runtime::get_named_arg("admin");
    let self_package_hash: String = runtime::get_named_arg("self_package_hash");

    runtime::put_key(ADMIN_KEY, storage::new_uref(admin).into());
    runtime::put_key(
        SELF_PACKAGE_KEY,
        storage::new_uref(self_package_hash).into(),
    );

    storage::new_dictionary(REC_COMMITMENT).unwrap_or_revert();
    storage::new_dictionary(REC_PROOF_HASH).unwrap_or_revert();
    storage::new_dictionary(REC_MIN).unwrap_or_revert();
    storage::new_dictionary(REC_MAX).unwrap_or_revert();
    storage::new_dictionary(REC_ARBITER_SET_HEX).unwrap_or_revert();
    storage::new_dictionary(REC_THRESHOLD).unwrap_or_revert();
    storage::new_dictionary(REC_ATTEST_COUNT).unwrap_or_revert();
    storage::new_dictionary(REC_ATTESTERS_HEX).unwrap_or_revert();
    storage::new_dictionary(REC_STATUS).unwrap_or_revert();
    storage::new_dictionary(REC_OPENED_AMOUNT).unwrap_or_revert();
    storage::new_dictionary(REC_OPENED_RANDOMNESS_HASH).unwrap_or_revert();
}

#[no_mangle]
pub extern "C" fn register_commitment() {
    let escrow_id_hex: String = runtime::get_named_arg("escrow_id_hex");
    let commitment_hex: String = runtime::get_named_arg("commitment_hex");
    let proof_hash_hex: String = runtime::get_named_arg("proof_hash_hex");
    let min_amount: u64 = runtime::get_named_arg("min_amount");
    let max_amount: u64 = runtime::get_named_arg("max_amount");
    let arbiter_set_hex: Vec<String> = runtime::get_named_arg("arbiter_set_hex");
    let threshold: u32 = runtime::get_named_arg("threshold");

    if escrow_id_hex.len() != 64 {
        runtime::revert(ApiError::User(ERR_HEX_DECODE));
    }
    let commitment_bytes = hex_decode(&commitment_hex);
    if commitment_bytes.is_empty() || commitment_bytes.len() > COMMITMENT_MAX_LEN {
        runtime::revert(ApiError::User(ERR_INVALID_COMMITMENT));
    }
    if proof_hash_hex.len() != HASH_LEN * 2 {
        runtime::revert(ApiError::User(ERR_INVALID_PROOF_HASH));
    }
    let proof_hash_bytes = hex_decode(&proof_hash_hex);
    if proof_hash_bytes.iter().all(|b| *b == 0) {
        runtime::revert(ApiError::User(ERR_INVALID_PROOF_HASH));
    }
    if min_amount > max_amount || max_amount == 0 {
        runtime::revert(ApiError::User(ERR_INVALID_RANGE));
    }
    if arbiter_set_hex.is_empty() || arbiter_set_hex.len() > MAX_ARBITERS {
        runtime::revert(ApiError::User(ERR_TOO_MANY_ARBITERS));
    }
    if threshold == 0 || (threshold as usize) > arbiter_set_hex.len() {
        runtime::revert(ApiError::User(ERR_THRESHOLD_UNMET));
    }
    // Deduplicate arbiter set (case-sensitive).
    let mut seen: Vec<String> = Vec::with_capacity(arbiter_set_hex.len());
    for k in &arbiter_set_hex {
        if seen.iter().any(|s| s == k) {
            runtime::revert(ApiError::User(ERR_TOO_MANY_ARBITERS));
        }
        seen.push(k.clone());
    }

    let k = escrow_key(&escrow_id_hex);
    if record_exists(&k) {
        runtime::revert(ApiError::User(ERR_ALREADY_REGISTERED));
    }

    dict_put(REC_COMMITMENT, &k, commitment_hex);
    dict_put(REC_PROOF_HASH, &k, proof_hash_hex);
    dict_put(REC_MIN, &k, min_amount);
    dict_put(REC_MAX, &k, max_amount);
    dict_put(REC_ARBITER_SET_HEX, &k, arbiter_set_hex);
    dict_put(REC_THRESHOLD, &k, threshold);
    dict_put(REC_ATTEST_COUNT, &k, 0u32);
    dict_put(REC_ATTESTERS_HEX, &k, Vec::<String>::new());
    dict_put(REC_STATUS, &k, STATUS_PENDING);
}

#[no_mangle]
pub extern "C" fn attest() {
    let escrow_id_hex: String = runtime::get_named_arg("escrow_id_hex");
    let attester_hex: String = runtime::get_named_arg("attester_hex");
    let signature_hex: String = runtime::get_named_arg("signature_hex");

    let k = escrow_key(&escrow_id_hex);
    if !record_exists(&k) {
        runtime::revert(ApiError::User(ERR_UNKNOWN_ESCROW));
    }
    require_status(read_status(&k), &[STATUS_PENDING]);

    let arbiter_set: Vec<String> = dict_get(REC_ARBITER_SET_HEX, &k)
        .unwrap_or_revert_with(ApiError::User(ERR_UNKNOWN_ESCROW));
    if !pk_in_set(&attester_hex, &arbiter_set) {
        runtime::revert(ApiError::User(ERR_ARBITER_NOT_IN_SET));
    }
    let mut attesters: Vec<String> =
        dict_get(REC_ATTESTERS_HEX, &k).unwrap_or_default();
    if pk_in_set(&attester_hex, &attesters) {
        runtime::revert(ApiError::User(ERR_ARBITER_DUPLICATE_ATTEST));
    }

    let commitment_hex: String = dict_get(REC_COMMITMENT, &k)
        .unwrap_or_revert_with(ApiError::User(ERR_UNKNOWN_ESCROW));
    let proof_hash_hex: String = dict_get(REC_PROOF_HASH, &k)
        .unwrap_or_revert_with(ApiError::User(ERR_UNKNOWN_ESCROW));
    let min_amount: u64 = dict_get(REC_MIN, &k)
        .unwrap_or_revert_with(ApiError::User(ERR_UNKNOWN_ESCROW));
    let max_amount: u64 = dict_get(REC_MAX, &k)
        .unwrap_or_revert_with(ApiError::User(ERR_UNKNOWN_ESCROW));

    let msg = attest_preimage(
        &escrow_id_hex,
        &commitment_hex,
        &proof_hash_hex,
        min_amount,
        max_amount,
    );
    verify_signature(&attester_hex, &signature_hex, &msg);

    attesters.push(attester_hex);
    let new_count = attesters.len() as u32;
    dict_put(REC_ATTESTERS_HEX, &k, attesters);
    dict_put(REC_ATTEST_COUNT, &k, new_count);
}

#[no_mangle]
pub extern "C" fn finalize() {
    let escrow_id_hex: String = runtime::get_named_arg("escrow_id_hex");
    let k = escrow_key(&escrow_id_hex);
    if !record_exists(&k) {
        runtime::revert(ApiError::User(ERR_UNKNOWN_ESCROW));
    }
    require_status(read_status(&k), &[STATUS_PENDING]);

    let count: u32 = dict_get(REC_ATTEST_COUNT, &k).unwrap_or(0);
    let threshold: u32 = dict_get(REC_THRESHOLD, &k)
        .unwrap_or_revert_with(ApiError::User(ERR_UNKNOWN_ESCROW));
    if count < threshold {
        runtime::revert(ApiError::User(ERR_THRESHOLD_UNMET));
    }
    dict_put(REC_STATUS, &k, STATUS_VERIFIED);
}

#[no_mangle]
pub extern "C" fn open() {
    let escrow_id_hex: String = runtime::get_named_arg("escrow_id_hex");
    let amount: u64 = runtime::get_named_arg("amount");
    let randomness_hash_hex: String = runtime::get_named_arg("randomness_hash_hex");

    let k = escrow_key(&escrow_id_hex);
    if !record_exists(&k) {
        runtime::revert(ApiError::User(ERR_UNKNOWN_ESCROW));
    }
    require_status(read_status(&k), &[STATUS_VERIFIED]);

    if randomness_hash_hex.len() != HASH_LEN * 2 {
        runtime::revert(ApiError::User(ERR_INVALID_RANDOMNESS_HASH));
    }
    let rh_bytes = hex_decode(&randomness_hash_hex);
    if rh_bytes.iter().all(|b| *b == 0) {
        runtime::revert(ApiError::User(ERR_INVALID_RANDOMNESS_HASH));
    }
    let min_amount: u64 = dict_get(REC_MIN, &k)
        .unwrap_or_revert_with(ApiError::User(ERR_UNKNOWN_ESCROW));
    let max_amount: u64 = dict_get(REC_MAX, &k)
        .unwrap_or_revert_with(ApiError::User(ERR_UNKNOWN_ESCROW));
    if amount < min_amount || amount > max_amount {
        runtime::revert(ApiError::User(ERR_AMOUNT_OUT_OF_RANGE));
    }

    dict_put(REC_OPENED_AMOUNT, &k, amount);
    dict_put(REC_OPENED_RANDOMNESS_HASH, &k, randomness_hash_hex);
    dict_put(REC_STATUS, &k, STATUS_OPENED);
}

#[no_mangle]
pub extern "C" fn mark_fraud() {
    let escrow_id_hex: String = runtime::get_named_arg("escrow_id_hex");
    let attester_hex: String = runtime::get_named_arg("attester_hex");
    let signature_hex: String = runtime::get_named_arg("signature_hex");
    let reason_hash_hex: String = runtime::get_named_arg("reason_hash_hex");

    if reason_hash_hex.len() != HASH_LEN * 2 {
        runtime::revert(ApiError::User(ERR_INVALID_PROOF_HASH));
    }
    let k = escrow_key(&escrow_id_hex);
    if !record_exists(&k) {
        runtime::revert(ApiError::User(ERR_UNKNOWN_ESCROW));
    }
    require_status(
        read_status(&k),
        &[STATUS_PENDING, STATUS_VERIFIED, STATUS_OPENED],
    );

    let arbiter_set: Vec<String> = dict_get(REC_ARBITER_SET_HEX, &k)
        .unwrap_or_revert_with(ApiError::User(ERR_UNKNOWN_ESCROW));
    if !pk_in_set(&attester_hex, &arbiter_set) {
        runtime::revert(ApiError::User(ERR_ARBITER_NOT_IN_SET));
    }
    let commitment_hex: String = dict_get(REC_COMMITMENT, &k)
        .unwrap_or_revert_with(ApiError::User(ERR_UNKNOWN_ESCROW));
    let proof_hash_hex: String = dict_get(REC_PROOF_HASH, &k)
        .unwrap_or_revert_with(ApiError::User(ERR_UNKNOWN_ESCROW));

    let msg = fraud_preimage(&escrow_id_hex, &commitment_hex, &proof_hash_hex, &reason_hash_hex);
    verify_signature(&attester_hex, &signature_hex, &msg);
    dict_put(REC_STATUS, &k, STATUS_FRAUD);
}

// ── Read entry points ────────────────────────────────────────────────

#[no_mangle]
pub extern "C" fn get_status_ep() {
    let escrow_id_hex: String = runtime::get_named_arg("escrow_id_hex");
    let s = read_status(&escrow_key(&escrow_id_hex));
    runtime::ret(CLValue::from_t(s).unwrap_or_revert());
}

#[no_mangle]
pub extern "C" fn get_commitment_ep() {
    let escrow_id_hex: String = runtime::get_named_arg("escrow_id_hex");
    let c: String = dict_get(REC_COMMITMENT, &escrow_key(&escrow_id_hex)).unwrap_or_default();
    runtime::ret(CLValue::from_t(c).unwrap_or_revert());
}

#[no_mangle]
pub extern "C" fn get_attestation_count_ep() {
    let escrow_id_hex: String = runtime::get_named_arg("escrow_id_hex");
    let c: u32 = dict_get(REC_ATTEST_COUNT, &escrow_key(&escrow_id_hex)).unwrap_or(0);
    runtime::ret(CLValue::from_t(c).unwrap_or_revert());
}

#[no_mangle]
pub extern "C" fn get_opened_amount_ep() {
    let escrow_id_hex: String = runtime::get_named_arg("escrow_id_hex");
    let a: u64 = dict_get(REC_OPENED_AMOUNT, &escrow_key(&escrow_id_hex)).unwrap_or(0);
    runtime::ret(CLValue::from_t(a).unwrap_or_revert());
}

#[no_mangle]
pub extern "C" fn get_range_ep() {
    let escrow_id_hex: String = runtime::get_named_arg("escrow_id_hex");
    let k = escrow_key(&escrow_id_hex);
    let min: u64 = dict_get(REC_MIN, &k).unwrap_or(0);
    let max: u64 = dict_get(REC_MAX, &k).unwrap_or(0);
    runtime::ret(CLValue::from_t((min, max)).unwrap_or_revert());
}

// ══════════════════════════════════════════════════════════════════════
// call() — install & init
// ══════════════════════════════════════════════════════════════════════

#[no_mangle]
pub extern "C" fn call() {
    let admin: String = runtime::get_named_arg("admin");

    let ep = |name: &str, params: Vec<Parameter>, ret: CLType| {
        EntityEntryPoint::new(
            name.to_string(),
            params,
            ret,
            EntryPointAccess::Public,
            EntryPointType::Called,
            EntryPointPayment::Caller,
        )
    };

    let mut entry_points = EntryPoints::new();

    entry_points.add_entry_point(ep(
        "init",
        vec![
            Parameter::new("admin", CLType::String),
            Parameter::new("self_package_hash", CLType::String),
        ],
        CLType::Unit,
    ));

    entry_points.add_entry_point(ep(
        "register_commitment",
        vec![
            Parameter::new("escrow_id_hex", CLType::String),
            Parameter::new("commitment_hex", CLType::String),
            Parameter::new("proof_hash_hex", CLType::String),
            Parameter::new("min_amount", CLType::U64),
            Parameter::new("max_amount", CLType::U64),
            Parameter::new(
                "arbiter_set_hex",
                CLType::List(Box::new(CLType::String)),
            ),
            Parameter::new("threshold", CLType::U32),
        ],
        CLType::Unit,
    ));

    entry_points.add_entry_point(ep(
        "attest",
        vec![
            Parameter::new("escrow_id_hex", CLType::String),
            Parameter::new("attester_hex", CLType::String),
            Parameter::new("signature_hex", CLType::String),
        ],
        CLType::Unit,
    ));

    entry_points.add_entry_point(ep(
        "finalize",
        vec![Parameter::new("escrow_id_hex", CLType::String)],
        CLType::Unit,
    ));

    entry_points.add_entry_point(ep(
        "open",
        vec![
            Parameter::new("escrow_id_hex", CLType::String),
            Parameter::new("amount", CLType::U64),
            Parameter::new("randomness_hash_hex", CLType::String),
        ],
        CLType::Unit,
    ));

    entry_points.add_entry_point(ep(
        "mark_fraud",
        vec![
            Parameter::new("escrow_id_hex", CLType::String),
            Parameter::new("attester_hex", CLType::String),
            Parameter::new("signature_hex", CLType::String),
            Parameter::new("reason_hash_hex", CLType::String),
        ],
        CLType::Unit,
    ));

    entry_points.add_entry_point(ep(
        "get_status_ep",
        vec![Parameter::new("escrow_id_hex", CLType::String)],
        CLType::U8,
    ));
    entry_points.add_entry_point(ep(
        "get_commitment_ep",
        vec![Parameter::new("escrow_id_hex", CLType::String)],
        CLType::String,
    ));
    entry_points.add_entry_point(ep(
        "get_attestation_count_ep",
        vec![Parameter::new("escrow_id_hex", CLType::String)],
        CLType::U32,
    ));
    entry_points.add_entry_point(ep(
        "get_opened_amount_ep",
        vec![Parameter::new("escrow_id_hex", CLType::String)],
        CLType::U64,
    ));
    entry_points.add_entry_point(ep(
        "get_range_ep",
        vec![Parameter::new("escrow_id_hex", CLType::String)],
        CLType::Tuple2([Box::new(CLType::U64), Box::new(CLType::U64)]),
    ));

    let (contract_hash, _access_uref) = storage::new_contract(
        entry_points,
        Some(NamedKeys::new()),
        Some("range_proof_registry_package".to_string()),
        Some("range_proof_registry_access".to_string()),
        None,
    );

    let pkg_hash: ContractPackageHash = runtime::get_key("range_proof_registry_package")
        .unwrap_or_revert_with(ApiError::User(ERR_MISSING_KEY))
        .into_hash_addr()
        .map(ContractPackageHash::new)
        .unwrap_or_revert_with(ApiError::User(ERR_MISSING_KEY));
    let pkg_hex = hex_lower(pkg_hash.value().as_slice());

    let _: () = runtime::call_contract(contract_hash, "init", {
        let mut args = casper_types::RuntimeArgs::new();
        args.insert("admin", admin).unwrap();
        args.insert("self_package_hash", pkg_hex).unwrap();
        args
    });
}
