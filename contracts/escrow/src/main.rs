#![no_std]
#![no_main]

extern crate alloc;

use alloc::string::{String, ToString};
use alloc::vec;
use alloc::vec::Vec;

use casper_contract::contract_api::{runtime, storage, system};
use casper_contract::unwrap_or_revert::UnwrapOrRevert;
use casper_types::account::AccountHash;
use casper_types::contracts::NamedKeys;
use casper_types::crypto::{self, AsymmetricType, PublicKey, Signature};
use casper_types::{EntryPointPayment, 
    ApiError, CLType, CLValue, EntityEntryPoint, EntryPointAccess, EntryPointType, EntryPoints, Key,
    Parameter, URef, U512,
};

// ── Error codes ──────────────────────────────────────────────────────

const ERR_ESCROW_NOT_FOUND: u16 = 1;
const ERR_UNAUTHORIZED: u16 = 2;
const ERR_ALREADY_DISPUTED: u16 = 4;
const ERR_INVALID_SIGNATURE: u16 = 5;
const ERR_FEE_TOO_HIGH: u16 = 7;
const ERR_INVALID_STATUS: u16 = 8;
const ERR_TTL_OUT_OF_RANGE: u16 = 10;
const ERR_DUPLICATE_HASH: u16 = 11;
const ERR_INSUFFICIENT_SIGS: u16 = 12;
const ERR_ZERO_AMOUNT: u16 = 13;
const ERR_POOL_FROZEN: u16 = 14;
const ERR_ALREADY_COMMITTED: u16 = 15;
const ERR_NO_COMMIT: u16 = 16;
const ERR_INVALID_PREIMAGE: u16 = 17;
const ERR_ALREADY_REVEALED: u16 = 18;
const ERR_CAP_EXCEEDED: u16 = 19;
const ERR_FEE_EXCEEDS_AMOUNT: u16 = 20;

// ── Storage keys ─────────────────────────────────────────────────────

const ESCROWS_DICT: &str = "escrows";
const REPUTATION_DICT: &str = "reputation";
const ARBITER_LIST: &str = "arbiter_list";
const ARBITER_THRESHOLD: &str = "arbiter_threshold";
const FEE_BPS_KEY: &str = "fee_bps";
const SWAP_COMMITS_DICT: &str = "swap_commits";
const POOL_FROZEN_KEY: &str = "pool_frozen";
const INSTALLER_KEY: &str = "installer";
const CONTRACT_PURSE: &str = "contract_purse";
const INSURANCE_PURSE: &str = "insurance_purse";
const RELEASE_CAP_KEY: &str = "release_cap";

// ── Constants ────────────────────────────────────────────────────────

const MIN_TTL: u64 = 60;
const MAX_TTL: u64 = 86_400;
const MAX_FEE_BPS: u64 = 1_000;
const DEFAULT_FEE_BPS: u64 = 200;
const DECAY_PERCENT_PER_WEEK: u64 = 5;
// 1000 CSPR (motes, 1 CSPR = 1e9 motes). Agent-signed release()/reveal_swap()
// calls at or below this cap execute unilaterally (as before). Anything
// above it is an A1 "no unilateral withdraw above cap" guard: the caller
// must additionally supply a quorum of arbiter signatures (same
// registered arbiter set / threshold used by resolve()), i.e. propose ->
// human/multisig approve, never a bare agent-key spend past the cap.
const DEFAULT_RELEASE_CAP_MOTES: u64 = 1_000_000_000_000;

const STATUS_PENDING: u8 = 0;
const STATUS_RELEASED: u8 = 1;
const STATUS_REFUNDED: u8 = 2;
const STATUS_EXPIRED: u8 = 3;
const STATUS_DISPUTED: u8 = 4;
const STATUS_RESOLVED: u8 = 5;

// ── Helpers ──────────────────────────────────────────────────────────

fn read_installer() -> AccountHash {
    let key = runtime::get_key(INSTALLER_KEY).unwrap_or_revert();
    key.into_account().unwrap_or_revert()
}

fn read_fee_bps() -> u64 {
    let uref = runtime::get_key(FEE_BPS_KEY)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    storage::read::<u64>(uref)
        .unwrap_or_revert()
        .unwrap_or(DEFAULT_FEE_BPS)
}

fn get_dict_uref(name: &str) -> URef {
    // Casper 2.2.x (audit-082): new_dictionary is disallowed in session/install context (call()).
    // Dicts and purses are lazily created inside entry points (Called context).
    match runtime::get_key(name) {
        Some(key) => key.into_uref().unwrap_or_revert(),
        None => storage::new_dictionary(name).unwrap_or_revert(),
    }
}

fn reputation_score(completed: u64, disputed: u64, weeks_inactive: u64) -> u64 {
    if completed == 0 {
        return 50;
    }
    let base = 100u64.saturating_sub(disputed.saturating_mul(10).min(50));
    let decay = DECAY_PERCENT_PER_WEEK
        .saturating_mul(weeks_inactive)
        .min(50);
    let score = base.saturating_sub(base.saturating_mul(decay) / 100);
    score.min(100)
}

/// Store escrow fields in the dictionary as a nested triple of triples.
/// Layout: ((sender, receiver, amount_str), (service_hash, status, created_at), (ttl, fee_bps))
/// fee_bps is captured at creation time to prevent recalculation drift.
type EscrowRecord = ((String, String, String), (String, u64, u64), (u64, u64));

/// Store reputation as: ((completed, disputed, slashed), (last_active, score))
type RepRecord = ((u64, u64, u64), (u64, u64));

fn read_escrow(dict: URef, key: &str) -> EscrowRecord {
    storage::dictionary_get::<EscrowRecord>(dict, key)
        .unwrap_or_revert()
        .unwrap_or_revert_with(ApiError::User(ERR_ESCROW_NOT_FOUND))
}

fn write_escrow(dict: URef, key: &str, record: EscrowRecord) {
    storage::dictionary_put(dict, key, record);
}

fn read_rep(dict: URef, key: &str) -> RepRecord {
    storage::dictionary_get::<RepRecord>(dict, key)
        .unwrap_or_revert()
        .unwrap_or(((0, 0, 0), (0, 50)))
}

fn write_rep(dict: URef, key: &str, record: RepRecord) {
    storage::dictionary_put(dict, key, record);
}

fn parse_u512(s: &str) -> U512 {
    match U512::from_dec_str(s) {
        Ok(v) => v,
        Err(_) => runtime::revert(ApiError::User(ERR_ESCROW_NOT_FOUND)),
    }
}

fn hex_decode_32(s: &str) -> [u8; 32] {
    // runtime::get_caller().to_string() returns raw lowercase hex, not "account-hash-{hex}"
    let mut out = [0u8; 32];
    for (i, chunk) in s.as_bytes().chunks(2).enumerate() {
        if i >= 32 { break; }
        let hi = (chunk[0] as char).to_digit(16).unwrap_or(0) as u8;
        let lo = chunk.get(1)
            .and_then(|&b| (b as char).to_digit(16))
            .unwrap_or(0) as u8;
        out[i] = (hi << 4) | lo;
    }
    out
}

fn parse_account(s: &str) -> AccountHash {
    // Try formatted "account-hash-{hex}" first; fall back to raw hex.
    match AccountHash::from_formatted_str(s) {
        Ok(v) => v,
        Err(_) => AccountHash::new(hex_decode_32(s)),
    }
}

fn require_not_frozen() {
    let uref = runtime::get_key(POOL_FROZEN_KEY)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    let frozen: bool = storage::read(uref).unwrap_or_revert().unwrap_or(false);
    if frozen {
        runtime::revert(ApiError::User(ERR_POOL_FROZEN));
    }
}

fn compute_fee(amount: U512, bps: u64) -> U512 {
    amount * U512::from(bps) / U512::from(10_000u64)
}

/// Defense-in-depth: `compute_fee` can never mathematically exceed `amount`
/// given `bps <= MAX_FEE_BPS` (10%), but a future upgrade raising that cap,
/// or any other code path computing `insurance_fee` differently, must not
/// be able to silently underflow this subtraction (wrapping to a huge
/// U512 value) -- revert explicitly instead.
fn checked_deduct_fee(amount: U512, insurance_fee: U512) -> U512 {
    amount
        .checked_sub(insurance_fee)
        .unwrap_or_revert_with(ApiError::User(ERR_FEE_EXCEEDS_AMOUNT))
}

/// Reads the release cap (motes). Defensive by design: `release_cap` is a
/// named key introduced after this contract's original install, and
/// Casper's `add_contract_version` upgrade path (see `call()`) does not
/// retroactively add new named keys to an already-deployed entity. Rather
/// than requiring every upgraded entity to have been re-initialized with
/// this exact key (fragile / easy to silently break release() for
/// existing deployments), fall back to the default cap if the key is
/// missing instead of reverting. `set_release_cap()` self-heals the key
/// into existence (create-if-absent) the first time an installer calls it.
fn read_release_cap() -> U512 {
    let cap_motes = match runtime::get_key(RELEASE_CAP_KEY) {
        Some(key) => {
            let uref = key.into_uref().unwrap_or_revert();
            // Defensive on type mismatch too, not just a missing key: if some
            // other code path ever wrote `release_cap` with a different
            // CLValue type than u64, `storage::read::<u64>` returns
            // Err(bytesrepr::Error) rather than panicking the whole
            // release()/reveal_swap() flow. Treat any read failure the same
            // as "key absent" -- fall back to the default cap -- since a
            // release cap misconfiguration should never be able to brick
            // fund release entirely.
            match storage::read::<u64>(uref) {
                Ok(Some(v)) => v,
                _ => DEFAULT_RELEASE_CAP_MOTES,
            }
        }
        None => DEFAULT_RELEASE_CAP_MOTES,
    };
    U512::from(cap_motes)
}

/// Canonical message an arbiter signs to cast a resolve() vote. Binding the
/// exact service_hash and verdict into the signed message prevents a vote
/// signature from being replayed for a different escrow or a different
/// outcome on the same escrow.
fn build_resolve_message(service_hash: &str, in_favor_of: &str) -> String {
    let mut msg = String::from("resolve:");
    msg.push_str(service_hash);
    msg.push(':');
    msg.push_str(in_favor_of);
    msg
}

/// Canonical message an arbiter signs to approve an above-cap release/
/// reveal_swap call. `action` distinguishes the two entry points so a
/// signature collected for one can't be replayed against the other, and
/// binding service_hash prevents replay across different escrows.
fn build_cap_approval_message(action: &str, service_hash: &str) -> String {
    let mut msg = String::from(action);
    msg.push(':');
    msg.push_str(service_hash);
    msg.push_str(":cap_approval");
    msg
}

/// Shared arbiter-quorum verification: checks that at least `threshold`
/// *distinct*, *registered* arbiters produced a valid Ed25519 signature
/// over `message`, and returns the number of valid, deduplicated votes.
/// Used by both `resolve()` (dispute verdict) and the above-cap guard in
/// `release()`/`reveal_swap()` (A1: no unilateral agent-key spend above
/// cap, only propose -> arbiter/human quorum approve).
fn verify_arbiter_quorum(
    message: &str,
    registered: &[String],
    pubkeys: &[String],
    signatures: &[String],
) -> u64 {
    if pubkeys.len() != signatures.len() {
        return 0;
    }
    let mut seen = Vec::<String>::new();
    let mut valid_count: u64 = 0;
    for (pubkey_hex, sig_hex) in pubkeys.iter().zip(signatures.iter()) {
        if seen.contains(pubkey_hex) || !registered.contains(pubkey_hex) {
            continue;
        }
        let Ok(public_key) = PublicKey::from_hex(pubkey_hex.as_bytes()) else {
            continue;
        };
        let Ok(signature) = Signature::from_hex(sig_hex.as_bytes()) else {
            continue;
        };
        if crypto::verify(message.as_bytes(), &signature, &public_key).is_ok() {
            valid_count += 1;
            seen.push(pubkey_hex.clone());
        }
    }
    valid_count
}

/// Reads the registered arbiter list + threshold (same source `resolve()`
/// uses) and reverts with `ERR_CAP_EXCEEDED` unless a valid quorum of
/// arbiter signatures over `build_cap_approval_message(action, service_hash)`
/// is present. Called only when the release amount exceeds the cap.
fn require_arbiter_cap_approval(
    action: &str,
    service_hash: &str,
    arbiter_pubkeys: &[String],
    arbiter_signatures: &[String],
) {
    let threshold_uref = runtime::get_key(ARBITER_THRESHOLD)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    let threshold: u64 = storage::read(threshold_uref).unwrap_or_revert().unwrap_or(3);

    let arb_uref = runtime::get_key(ARBITER_LIST)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    let registered: Vec<String> = storage::read(arb_uref).unwrap_or_revert().unwrap_or_default();

    let message = build_cap_approval_message(action, service_hash);
    let valid_count =
        verify_arbiter_quorum(&message, &registered, arbiter_pubkeys, arbiter_signatures);
    if valid_count < threshold {
        runtime::revert(ApiError::User(ERR_CAP_EXCEEDED));
    }
}

/// Hex-encode raw bytes (lowercase), no external crate needed.
fn hex_encode(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        out.push(HEX[(b >> 4) as usize] as char);
        out.push(HEX[(b & 0x0f) as usize] as char);
    }
    out
}

/// SHA-256 digest of `preimage`, hex-encoded. Used for the atomic-swap
/// hash-lock (commit_swap/reveal_swap): the sender commits this hash up
/// front, the receiver must later produce the exact preimage that hashes
/// to it (classic HTLC pattern) before funds release. Uses the audited
/// `sha2` crate (no_std) rather than a hand-rolled hash, since Casper's
/// contract host API does not expose a generic hash function to
/// arbitrary contract code (only blake2b internally for its own storage
/// keys, not callable from contract code).
fn sha256_hex(preimage: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    let digest = Sha256::digest(preimage);
    hex_encode(&digest)
}

/// Move the escrowed funds to `receiver`, mark the escrow released, and
/// bump the receiver's reputation. Shared by `release()` (sender-authorized)
/// and `reveal_swap()` (hash-lock-authorized) so both paths use one
/// audited fund-movement implementation instead of two copies that could
/// drift apart.
fn do_release_funds(
    dict: URef,
    service_hash: &str,
    sender_str: String,
    receiver_str: String,
    amount_str: String,
    created_at: u64,
    ttl: u64,
    stored_fee_bps: u64,
) {
    let amount = parse_u512(&amount_str);
    let insurance_fee = compute_fee(amount, stored_fee_bps);
    let net_amount = checked_deduct_fee(amount, insurance_fee);

    // Checks-effects-interactions: write the terminal status before the
    // outbound transfer (see module-level note on do_refund/resolve).
    let updated: EscrowRecord = (
        (sender_str, receiver_str.clone(), amount_str),
        (service_hash.to_string(), STATUS_RELEASED as u64, created_at),
        (ttl, stored_fee_bps),
    );
    write_escrow(dict, service_hash, updated);

    let receiver = parse_account(&receiver_str);
    let contract_purse = get_dict_uref(CONTRACT_PURSE);
    system::transfer_from_purse_to_account(contract_purse, receiver, net_amount, None)
        .unwrap_or_revert();

    let rep_dict = get_dict_uref(REPUTATION_DICT);
    let ((completed, disputed, slashed), (_, _)) = read_rep(rep_dict, &receiver_str);
    let new_completed = completed.saturating_add(1);
    let now: u64 = runtime::get_blocktime().into();
    let score = reputation_score(new_completed, disputed, 0);
    write_rep(
        rep_dict,
        &receiver_str,
        ((new_completed, disputed, slashed), (now, score)),
    );
}

// ── Entry points ─────────────────────────────────────────────────────

/// Lock CSPR in escrow until service completes or TTL expires.
#[no_mangle]
pub extern "C" fn escrow() {
    require_not_frozen();

    let sender = runtime::get_caller();
    let receiver: AccountHash = runtime::get_named_arg("receiver");
    let amount: U512 = runtime::get_named_arg("amount");
    let service_hash: String = runtime::get_named_arg("service_hash");
    let ttl: u64 = runtime::get_named_arg("ttl");
    let source_purse: URef = runtime::get_named_arg("source_purse");

    if amount.is_zero() {
        runtime::revert(ApiError::User(ERR_ZERO_AMOUNT));
    }
    if ttl < MIN_TTL || ttl > MAX_TTL {
        runtime::revert(ApiError::User(ERR_TTL_OUT_OF_RANGE));
    }

    let dict = get_dict_uref(ESCROWS_DICT);
    let existing: Option<EscrowRecord> =
        storage::dictionary_get(dict, &service_hash).unwrap_or_revert();
    if existing.is_some() {
        runtime::revert(ApiError::User(ERR_DUPLICATE_HASH));
    }

    // Capture fee at creation time to prevent drift if fee changes later
    let fee_bps = read_fee_bps();
    let insurance_fee = compute_fee(amount, fee_bps);
    let escrow_amount = checked_deduct_fee(amount, insurance_fee);

    let contract_purse = get_dict_uref(CONTRACT_PURSE);
    system::transfer_from_purse_to_purse(source_purse, contract_purse, escrow_amount, None)
        .unwrap_or_revert();

    if !insurance_fee.is_zero() {
        let ins_purse = get_dict_uref(INSURANCE_PURSE);
        system::transfer_from_purse_to_purse(source_purse, ins_purse, insurance_fee, None)
            .unwrap_or_revert();
    }

    let created_at: u64 = runtime::get_blocktime().into();
    let record: EscrowRecord = (
        (
            sender.to_string(),
            receiver.to_string(),
            amount.to_string(),
        ),
        (service_hash.clone(), STATUS_PENDING as u64, created_at),
        (ttl, fee_bps),
    );
    write_escrow(dict, &service_hash, record);
}

/// Release escrowed funds to the service provider. A1 guard: if `amount`
/// exceeds the on-chain release cap, the sender alone can no longer
/// authorize the transfer -- a quorum of registered-arbiter signatures
/// over `build_cap_approval_message("release", service_hash)` must also be
/// supplied (propose -> human/multisig approve for anything above cap).
#[no_mangle]
pub extern "C" fn release() {
    require_not_frozen();

    let service_hash: String = runtime::get_named_arg("service_hash");
    let arbiter_pubkeys: Vec<String> = runtime::get_named_arg("arbiter_pubkeys");
    let arbiter_signatures: Vec<String> = runtime::get_named_arg("arbiter_signatures");
    let caller = runtime::get_caller();

    let dict = get_dict_uref(ESCROWS_DICT);
    let ((sender_str, receiver_str, amount_str), (_, status, created_at), (ttl, stored_fee_bps)) =
        read_escrow(dict, &service_hash);

    if status != STATUS_PENDING as u64 {
        runtime::revert(ApiError::User(ERR_INVALID_STATUS));
    }
    if caller.to_string() != sender_str {
        runtime::revert(ApiError::User(ERR_UNAUTHORIZED));
    }

    let amount = parse_u512(&amount_str);
    if amount > read_release_cap() {
        require_arbiter_cap_approval(
            "release",
            &service_hash,
            &arbiter_pubkeys,
            &arbiter_signatures,
        );
    }

    do_release_funds(
        dict,
        &service_hash,
        sender_str,
        receiver_str,
        amount_str,
        created_at,
        ttl,
        stored_fee_bps,
    );
}

/// Commit a hash-lock for an atomic swap (HTLC pattern). Only the escrow's
/// sender may commit, and only once per escrow (no overwriting a hash after
/// the fact). `commit_hash` must be the hex-encoded SHA-256 digest of a
/// preimage the sender will disclose off-chain to the receiver once the
/// counter-condition (e.g. a transfer on another chain) is satisfied.
#[no_mangle]
pub extern "C" fn commit_swap() {
    require_not_frozen();

    let service_hash: String = runtime::get_named_arg("service_hash");
    let commit_hash: String = runtime::get_named_arg("commit_hash");
    let caller = runtime::get_caller();

    let dict = get_dict_uref(ESCROWS_DICT);
    let ((sender_str, _, _), (_, status, _), _) = read_escrow(dict, &service_hash);

    if status != STATUS_PENDING as u64 {
        runtime::revert(ApiError::User(ERR_INVALID_STATUS));
    }
    if caller.to_string() != sender_str {
        runtime::revert(ApiError::User(ERR_UNAUTHORIZED));
    }

    let commits = get_dict_uref(SWAP_COMMITS_DICT);
    let existing: Option<(String, bool)> =
        storage::dictionary_get(commits, &service_hash).unwrap_or_revert();
    if existing.is_some() {
        runtime::revert(ApiError::User(ERR_ALREADY_COMMITTED));
    }
    // (commit_hash, revealed)
    storage::dictionary_put(commits, &service_hash, (commit_hash, false));
}

/// Reveal the preimage for a previously committed hash-lock. Anyone who
/// knows the correct preimage may call this (matches the HTLC model: the
/// secret itself is the authorization, not the caller's identity) -- the
/// contract verifies `sha256(preimage) == commit_hash` on-chain before
/// releasing funds to the escrow's receiver. This replaces the fully
/// backend-simulated atomic-swap flow that previously just flipped
/// in-memory state with no on-chain hash verification at all.
/// A1 guard: same above-cap arbiter-quorum requirement as `release()`,
/// checked against `build_cap_approval_message("reveal_swap", service_hash)`
/// -- the HTLC secret alone is no longer sufficient authorization for an
/// above-cap payout, closing the same unilateral-withdraw gap on this
/// second release path.
#[no_mangle]
pub extern "C" fn reveal_swap() {
    require_not_frozen();

    let service_hash: String = runtime::get_named_arg("service_hash");
    let preimage: String = runtime::get_named_arg("preimage");
    let arbiter_pubkeys: Vec<String> = runtime::get_named_arg("arbiter_pubkeys");
    let arbiter_signatures: Vec<String> = runtime::get_named_arg("arbiter_signatures");

    let commits = get_dict_uref(SWAP_COMMITS_DICT);
    let (commit_hash, revealed): (String, bool) =
        storage::dictionary_get(commits, &service_hash)
            .unwrap_or_revert()
            .unwrap_or_revert_with(ApiError::User(ERR_NO_COMMIT));
    if revealed {
        runtime::revert(ApiError::User(ERR_ALREADY_REVEALED));
    }

    let computed = sha256_hex(preimage.as_bytes());
    if computed != commit_hash {
        runtime::revert(ApiError::User(ERR_INVALID_PREIMAGE));
    }

    let dict = get_dict_uref(ESCROWS_DICT);
    let ((sender_str, receiver_str, amount_str), (_, status, created_at), (ttl, stored_fee_bps)) =
        read_escrow(dict, &service_hash);
    if status != STATUS_PENDING as u64 {
        runtime::revert(ApiError::User(ERR_INVALID_STATUS));
    }

    let amount = parse_u512(&amount_str);
    if amount > read_release_cap() {
        require_arbiter_cap_approval(
            "reveal_swap",
            &service_hash,
            &arbiter_pubkeys,
            &arbiter_signatures,
        );
    }

    storage::dictionary_put(commits, &service_hash, (commit_hash, true));

    do_release_funds(
        dict,
        &service_hash,
        sender_str,
        receiver_str,
        amount_str,
        created_at,
        ttl,
        stored_fee_bps,
    );
}

/// Refund escrowed funds to the sender when TTL expires.
#[no_mangle]
pub extern "C" fn refund() {
    require_not_frozen();

    let service_hash: String = runtime::get_named_arg("service_hash");
    let caller = runtime::get_caller();

    let dict = get_dict_uref(ESCROWS_DICT);
    let ((sender_str, receiver_str, amount_str), (_, status, created_at), (ttl, stored_fee_bps)) =
        read_escrow(dict, &service_hash);

    if status != STATUS_PENDING as u64 {
        runtime::revert(ApiError::User(ERR_INVALID_STATUS));
    }

    let now: u64 = runtime::get_blocktime().into();
    let is_expired = now > created_at + ttl;
    let is_sender = caller.to_string() == sender_str;

    if !is_expired && !is_sender {
        runtime::revert(ApiError::User(ERR_UNAUTHORIZED));
    }

    // Use fee_bps captured at escrow creation
    let amount = parse_u512(&amount_str);
    let insurance_fee = compute_fee(amount, stored_fee_bps);
    let refund_amount = checked_deduct_fee(amount, insurance_fee);

    let new_status = if is_expired {
        STATUS_EXPIRED as u64
    } else {
        STATUS_REFUNDED as u64
    };

    // Checks-effects-interactions: record the terminal status *before*
    // transferring funds out, so the escrow can never be read/acted on
    // again as still-pending even if the transfer somehow failed to
    // finish cleanly. Casper's execution model doesn't allow a
    // synchronous callback into this contract mid-transfer (the system
    // call below has no user-code reentry path), but this ordering is
    // the standard hardening pattern regardless and costs nothing.
    let updated: EscrowRecord = (
        (sender_str.clone(), receiver_str, amount_str),
        (service_hash.clone(), new_status, created_at),
        (ttl, stored_fee_bps),
    );
    write_escrow(dict, &service_hash, updated);

    let sender = parse_account(&sender_str);
    let contract_purse = get_dict_uref(CONTRACT_PURSE);
    system::transfer_from_purse_to_account(contract_purse, sender, refund_amount, None)
        .unwrap_or_revert();
}

/// Open a dispute for a pending escrow.
/// Only the sender or receiver of the escrow may open a dispute.
#[no_mangle]
pub extern "C" fn dispute() {
    require_not_frozen();

    let service_hash: String = runtime::get_named_arg("service_hash");
    let caller = runtime::get_caller();

    let dict = get_dict_uref(ESCROWS_DICT);
    let ((sender_str, receiver_str, amount_str), (_, status, created_at), (ttl, fee_bps)) =
        read_escrow(dict, &service_hash);

    if status != STATUS_PENDING as u64 {
        runtime::revert(ApiError::User(ERR_INVALID_STATUS));
    }

    // Only sender or receiver may dispute — prevents third-party griefing
    let caller_str = caller.to_string();
    if caller_str != sender_str && caller_str != receiver_str {
        runtime::revert(ApiError::User(ERR_UNAUTHORIZED));
    }

    let updated: EscrowRecord = (
        (sender_str.clone(), receiver_str, amount_str),
        (service_hash.clone(), STATUS_DISPUTED as u64, created_at),
        (ttl, fee_bps),
    );
    write_escrow(dict, &service_hash, updated);

    // Penalize disputing party's reputation
    let rep_dict = get_dict_uref(REPUTATION_DICT);
    let ((completed, disputed, slashed), (last_active, _)) = read_rep(rep_dict, &caller_str);
    let new_disputed = disputed.saturating_add(1);
    let score = reputation_score(completed, new_disputed, 0);
    write_rep(
        rep_dict,
        &caller_str,
        ((completed, new_disputed, slashed), (last_active, score)),
    );
}

/// Resolve dispute via 3-of-5 multisig arbitration.
/// Each arbiter's vote is a real Ed25519 signature (verified on-chain via
/// `casper_types::crypto::verify`) over the canonical message
/// `"resolve:{service_hash}:{in_favor_of}"`, signed with that arbiter's
/// registered keypair. This binds every vote to this specific escrow and
/// verdict -- a vote cannot be replayed for a different escrow/outcome or
/// forged without the arbiter's private key.
#[no_mangle]
pub extern "C" fn resolve() {
    require_not_frozen();

    let service_hash: String = runtime::get_named_arg("service_hash");
    let in_favor_of: String = runtime::get_named_arg("in_favor_of");
    // Hex-encoded (AsymmetricType::to_hex format, tag-prefixed) Ed25519
    // public keys and their corresponding signatures over the vote message.
    let arbiter_pubkeys: Vec<String> = runtime::get_named_arg("arbiter_pubkeys");
    let arbiter_signatures: Vec<String> = runtime::get_named_arg("arbiter_signatures");

    let dict = get_dict_uref(ESCROWS_DICT);
    let ((sender_str, receiver_str, amount_str), (_, status, created_at), (ttl, stored_fee_bps)) =
        read_escrow(dict, &service_hash);

    if status != STATUS_DISPUTED as u64 {
        runtime::revert(ApiError::User(ERR_ALREADY_DISPUTED));
    }

    let threshold_uref = runtime::get_key(ARBITER_THRESHOLD)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    let threshold: u64 = storage::read(threshold_uref).unwrap_or_revert().unwrap_or(3);

    if arbiter_pubkeys.len() != arbiter_signatures.len() {
        runtime::revert(ApiError::User(ERR_INVALID_SIGNATURE));
    }
    if (arbiter_pubkeys.len() as u64) < threshold {
        runtime::revert(ApiError::User(ERR_INSUFFICIENT_SIGS));
    }

    let arb_uref = runtime::get_key(ARBITER_LIST)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    // ARBITER_LIST stores each arbiter's hex-encoded Ed25519 public key
    // (registered via `set_arbiters`), not an account-hash -- a public key
    // is required to verify a signature, an account-hash is one-way and
    // cannot be reversed back into it.
    let registered: Vec<String> = storage::read(arb_uref).unwrap_or_revert().unwrap_or_default();

    let vote_message = build_resolve_message(&service_hash, &in_favor_of);

    // Verify each claimed vote's signature and deduplicate by public key so
    // a single arbiter's vote cannot be counted more than once.
    let mut seen = Vec::<String>::new();
    let mut valid_count: u64 = 0;
    for (pubkey_hex, sig_hex) in arbiter_pubkeys.iter().zip(arbiter_signatures.iter()) {
        if seen.contains(pubkey_hex) || !registered.contains(pubkey_hex) {
            continue;
        }
        let Ok(public_key) = PublicKey::from_hex(pubkey_hex.as_bytes()) else {
            continue;
        };
        let Ok(signature) = Signature::from_hex(sig_hex.as_bytes()) else {
            continue;
        };
        if crypto::verify(vote_message.as_bytes(), &signature, &public_key).is_ok() {
            valid_count += 1;
            seen.push(pubkey_hex.clone());
        }
    }
    if valid_count < threshold {
        runtime::revert(ApiError::User(ERR_INVALID_SIGNATURE));
    }

    // Use fee_bps captured at escrow creation
    let amount = parse_u512(&amount_str);
    let insurance_fee = compute_fee(amount, stored_fee_bps);
    let net_amount = checked_deduct_fee(amount, insurance_fee);

    let winner = if in_favor_of == "sender" {
        parse_account(&sender_str)
    } else {
        parse_account(&receiver_str)
    };

    // Checks-effects-interactions (see do_release_funds / refund()).
    let updated: EscrowRecord = (
        (sender_str, receiver_str, amount_str),
        (service_hash.clone(), STATUS_RESOLVED as u64, created_at),
        (ttl, stored_fee_bps),
    );
    write_escrow(dict, &service_hash, updated);

    let contract_purse = get_dict_uref(CONTRACT_PURSE);
    system::transfer_from_purse_to_account(contract_purse, winner, net_amount, None)
        .unwrap_or_revert();
}

/// Update the insurance fee (installer only, max 10%).
#[no_mangle]
pub extern "C" fn configure_fee() {
    let caller = runtime::get_caller();
    let installer = read_installer();
    if caller != installer {
        runtime::revert(ApiError::User(ERR_UNAUTHORIZED));
    }

    let new_fee_bps: u64 = runtime::get_named_arg("new_fee_bps");
    if new_fee_bps > MAX_FEE_BPS {
        runtime::revert(ApiError::User(ERR_FEE_TOO_HIGH));
    }

    let uref = runtime::get_key(FEE_BPS_KEY)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    storage::write(uref, new_fee_bps);
}

/// Update the A1 release cap in motes (installer only). Above this amount,
/// `release()`/`reveal_swap()` require an arbiter-quorum cap-approval on
/// top of their normal authorization (sender / correct HTLC preimage) --
/// see `require_arbiter_cap_approval`. Self-heals the `release_cap` named
/// key into existence on first call if this entity predates it (see
/// `read_release_cap` doc comment for why upgrades can't always add it).
#[no_mangle]
pub extern "C" fn set_release_cap() {
    let caller = runtime::get_caller();
    let installer = read_installer();
    if caller != installer {
        runtime::revert(ApiError::User(ERR_UNAUTHORIZED));
    }

    let new_cap_motes: u64 = runtime::get_named_arg("new_cap_motes");

    match runtime::get_key(RELEASE_CAP_KEY) {
        Some(key) => {
            let uref = key.into_uref().unwrap_or_revert();
            storage::write(uref, new_cap_motes);
        }
        None => {
            let uref = storage::new_uref(new_cap_motes);
            runtime::put_key(RELEASE_CAP_KEY, uref.into());
        }
    }
}

/// Register (replace) the on-chain arbiter list used by `resolve()`
/// (installer only). Overwrites the whole list -- pass the full desired
/// set of arbiter hex-encoded Ed25519 public keys (AsymmetricType::to_hex
/// format, tag-prefixed) each time. A public key (not an account-hash) is
/// required so `resolve()` can verify each arbiter's vote signature.
#[no_mangle]
pub extern "C" fn set_arbiters() {
    let caller = runtime::get_caller();
    let installer = read_installer();
    if caller != installer {
        runtime::revert(ApiError::User(ERR_UNAUTHORIZED));
    }

    let arbiters: Vec<String> = runtime::get_named_arg("arbiters");

    let uref = runtime::get_key(ARBITER_LIST)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    storage::write(uref, arbiters);
}

/// Freeze insurance pool payouts (installer only).
#[no_mangle]
pub extern "C" fn emergency_freeze() {
    let caller = runtime::get_caller();
    let installer = read_installer();
    if caller != installer {
        runtime::revert(ApiError::User(ERR_UNAUTHORIZED));
    }

    let uref = runtime::get_key(POOL_FROZEN_KEY)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    storage::write(uref, true);
}

/// Resume operations after `emergency_freeze` (installer only). Previously
/// freezing was one-way and required a contract upgrade to resume; this
/// entry point lets the installer clear the flag directly.
#[no_mangle]
pub extern "C" fn unfreeze() {
    let caller = runtime::get_caller();
    let installer = read_installer();
    if caller != installer {
        runtime::revert(ApiError::User(ERR_UNAUTHORIZED));
    }

    let uref = runtime::get_key(POOL_FROZEN_KEY)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    storage::write(uref, false);
}

/// Read escrow record by service hash.
#[no_mangle]
pub extern "C" fn get_escrow() {
    let service_hash: String = runtime::get_named_arg("service_hash");
    let dict = get_dict_uref(ESCROWS_DICT);
    let record = read_escrow(dict, &service_hash);
    let result = CLValue::from_t(record).unwrap_or_revert();
    runtime::ret(result);
}

/// Read reputation by agent account hash.
#[no_mangle]
pub extern "C" fn get_reputation() {
    let agent: String = runtime::get_named_arg("agent");
    let dict = get_dict_uref(REPUTATION_DICT);
    let rep = read_rep(dict, &agent);
    runtime::ret(CLValue::from_t(rep).unwrap_or_revert());
}

// ── Contract installation ────────────────────────────────────────────

#[no_mangle]
pub extern "C" fn call() {
    let installer = runtime::get_caller();

    // Casper 2.2.x: new_dictionary is disallowed in session/install context.
    // Dictionaries (escrows, reputation) are created lazily in entry points via get_dict_uref().
    let contract_purse = system::create_purse();
    let insurance_purse = system::create_purse();
    let fee_bps_uref = storage::new_uref(DEFAULT_FEE_BPS);
    let frozen_uref = storage::new_uref(false);
    let threshold_uref = storage::new_uref(3u64);
    let arbiter_uref = storage::new_uref(Vec::<String>::new());
    let release_cap_uref = storage::new_uref(DEFAULT_RELEASE_CAP_MOTES);

    let mut named_keys = NamedKeys::new();
    named_keys.insert(CONTRACT_PURSE.into(), contract_purse.into());
    named_keys.insert(INSURANCE_PURSE.into(), insurance_purse.into());
    named_keys.insert(FEE_BPS_KEY.into(), fee_bps_uref.into());
    named_keys.insert(POOL_FROZEN_KEY.into(), frozen_uref.into());
    named_keys.insert(ARBITER_THRESHOLD.into(), threshold_uref.into());
    named_keys.insert(ARBITER_LIST.into(), arbiter_uref.into());
    named_keys.insert(RELEASE_CAP_KEY.into(), release_cap_uref.into());
    named_keys.insert(INSTALLER_KEY.into(), Key::Account(installer));

    let mut entry_points = EntryPoints::new();
    entry_points.add_entry_point(EntityEntryPoint::new(
        "escrow",
        vec![
            Parameter::new("receiver", CLType::ByteArray(32)),
            Parameter::new("amount", CLType::U512),
            Parameter::new("service_hash", CLType::String),
            Parameter::new("ttl", CLType::U64),
            Parameter::new("source_purse", CLType::URef),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "release",
        vec![
            Parameter::new("service_hash", CLType::String),
            Parameter::new(
                "arbiter_pubkeys",
                CLType::List(alloc::boxed::Box::new(CLType::String)),
            ),
            Parameter::new(
                "arbiter_signatures",
                CLType::List(alloc::boxed::Box::new(CLType::String)),
            ),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "refund",
        vec![Parameter::new("service_hash", CLType::String)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "dispute",
        vec![Parameter::new("service_hash", CLType::String)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "commit_swap",
        vec![
            Parameter::new("service_hash", CLType::String),
            Parameter::new("commit_hash", CLType::String),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "reveal_swap",
        vec![
            Parameter::new("service_hash", CLType::String),
            Parameter::new("preimage", CLType::String),
            Parameter::new(
                "arbiter_pubkeys",
                CLType::List(alloc::boxed::Box::new(CLType::String)),
            ),
            Parameter::new(
                "arbiter_signatures",
                CLType::List(alloc::boxed::Box::new(CLType::String)),
            ),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "resolve",
        vec![
            Parameter::new("service_hash", CLType::String),
            Parameter::new("in_favor_of", CLType::String),
            Parameter::new(
                "arbiter_pubkeys",
                CLType::List(alloc::boxed::Box::new(CLType::String)),
            ),
            Parameter::new(
                "arbiter_signatures",
                CLType::List(alloc::boxed::Box::new(CLType::String)),
            ),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "set_arbiters",
        vec![Parameter::new(
            "arbiters",
            CLType::List(alloc::boxed::Box::new(CLType::String)),
        )],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "configure_fee",
        vec![Parameter::new("new_fee_bps", CLType::U64)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "set_release_cap",
        vec![Parameter::new("new_cap_motes", CLType::U64)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "emergency_freeze",
        vec![],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "unfreeze",
        vec![],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "get_escrow",
        vec![Parameter::new("service_hash", CLType::String)],
        CLType::Any,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "get_reputation",
        vec![Parameter::new("agent", CLType::String)],
        CLType::Any,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    // Upgrade path: if this account already has an `escrow_package_hash`
    // named key (i.e. we are re-running `call()` against an existing
    // deployment to add new entry points), add a new contract version to
    // that package instead of creating a brand-new package. This preserves
    // the existing contract hash's on-chain storage (escrows, reputation,
    // arbiter_list urefs etc.) -- only the entry-point set changes.
    if let Some(existing_package_key) = runtime::get_key("escrow_package_hash") {
        let package_hash_addr = existing_package_key
            .into_entity_hash_addr()
            .unwrap_or_revert();
        let package_hash: casper_types::contracts::ContractPackageHash =
            package_hash_addr.into();
        let (contract_hash, _) = storage::add_contract_version(
            package_hash,
            entry_points,
            NamedKeys::new(),
            alloc::collections::BTreeMap::new(),
        );
        runtime::put_key("escrow_contract", contract_hash.into());
        return;
    }

    let (contract_hash, _) = storage::new_contract(
        entry_points,
        Some(named_keys),
        Some("escrow_package_hash".into()),
        Some("escrow_access_uref".into()),
        None,
    );
    runtime::put_key("escrow_contract", contract_hash.into());
}
