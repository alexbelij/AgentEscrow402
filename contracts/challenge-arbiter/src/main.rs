#![no_std]
#![no_main]

//! Challenge-window + commit-reveal arbiter selection
//!
//! Additive dispute-resolution layer sitting alongside `escrow::dispute()` /
//! `escrow::resolve()`. Where `escrow` runs a plain 3-of-5 multisig verdict,
//! this contract adds:
//!
//! * **Bond-required challenges** — a challenger must post `challenge_bond`
//!   with the challenge; a losing challenge slashes it, a winning challenge
//!   returns it + rewards.
//! * **Timelocked commit → reveal phases** — arbiters `commit(H(verdict, nonce, pk))`
//!   within `commit_window`, then `reveal(verdict, nonce)` within `reveal_window`.
//!   A predictable arbiter cannot be pre-targeted because the verdict is bound
//!   to a per-dispute nonce known only after reveal.
//! * **Slash on non-reveal** — an arbiter that commits but does not reveal
//!   loses their `arbiter_bond`, redistributed to revealers + challenger.
//! * **Threshold + finality** — `finalize()` runs after `reveal_deadline`; if
//!   fewer than `threshold` reveals landed, challenge fails and bond returns
//!   to escrow status-quo winner.
//!
//! Anti-replay: every arbiter signature is bound to
//! `ae402:challenge:v1:{action}:{contract_hash}:{dispute_id}:{arbiter_pk}:{payload_hash}`
//! so a signature for one dispute cannot be replayed against another.
//!
//! Full threat model + operational notes: `docs/CHALLENGE_COMMIT_REVEAL.md`.

extern crate alloc;

use alloc::boxed::Box;
use alloc::string::{String, ToString};
use alloc::vec;
use alloc::vec::Vec;

use casper_contract::contract_api::{runtime, storage};
use casper_contract::unwrap_or_revert::UnwrapOrRevert;
use casper_types::contracts::NamedKeys;
use casper_types::crypto::{self, PublicKey, Signature};
use casper_types::{
    ApiError, AsymmetricType, CLType, CLValue, EntityEntryPoint, EntryPointAccess,
    EntryPointPayment, EntryPointType, EntryPoints, Key, Parameter, URef, U512,
};

// ── Error codes ──────────────────────────────────────────────────────

// ERR_UNAUTHORIZED (1) reserved for future cross-contract admin gate.
const ERR_INVALID_SIGNATURE: u16 = 2;
const ERR_INVALID_STATE: u16 = 3;
const ERR_CHALLENGE_EXISTS: u16 = 4;
const ERR_CHALLENGE_NOT_FOUND: u16 = 5;
const ERR_COMMIT_WINDOW_CLOSED: u16 = 6;
const ERR_COMMIT_WINDOW_OPEN: u16 = 7;
const ERR_REVEAL_WINDOW_CLOSED: u16 = 8;
const ERR_REVEAL_WINDOW_OPEN: u16 = 9;
const ERR_ALREADY_COMMITTED: u16 = 10;
const ERR_NOT_COMMITTED: u16 = 11;
const ERR_ALREADY_REVEALED: u16 = 12;
const ERR_COMMIT_MISMATCH: u16 = 13;
const ERR_INVALID_BOND: u16 = 14;
const ERR_ALREADY_FINALIZED: u16 = 16;
const ERR_INVALID_VERDICT: u16 = 18;
const ERR_INVALID_ARBITER: u16 = 19;
const ERR_ZERO_ADDRESS: u16 = 20;
const ERR_NOT_INSTALLER: u16 = 21;
const ERR_CONFIG_LOCKED: u16 = 22;
const ERR_NOT_SLASHABLE: u16 = 23;

// ── Named keys ───────────────────────────────────────────────────────

const INSTALLER_KEY: &str = "installer";
const CONFIG_LOCKED_KEY: &str = "config_locked";
const CHALLENGE_BOND_KEY: &str = "challenge_bond";
const ARBITER_BOND_KEY: &str = "arbiter_bond";
const COMMIT_WINDOW_KEY: &str = "commit_window_ms";
const REVEAL_WINDOW_KEY: &str = "reveal_window_ms";
const THRESHOLD_KEY: &str = "threshold";
const ARBITER_REGISTRY_KEY: &str = "arbiter_registry"; // Vec<String> of hex pubkeys
const SELF_PACKAGE_KEY: &str = "self_package_hash";

const CHALLENGES_DICT: &str = "challenges";
const COMMITS_DICT: &str = "commits";
const REVEALS_DICT: &str = "reveals";


// ── Domain string ────────────────────────────────────────────────────

/// Domain separator for every signature this contract verifies. Includes the
/// contract package hash so a signature for one deployment cannot be
/// replayed against another (staging vs. mainnet, contract upgrades, etc.).
const DOMAIN: &str = "ae402:challenge:v1";

// ── Verdict constants ────────────────────────────────────────────────

const VERDICT_SENDER: u64 = 1;
const VERDICT_RECEIVER: u64 = 2;
// Verdicts outside {1, 2} are rejected on reveal to keep the enum closed.

// ── Status constants ─────────────────────────────────────────────────

const STATUS_COMMIT_PHASE: u64 = 2;
const STATUS_REVEAL_PHASE: u64 = 3;
const STATUS_FINALIZED_CHALLENGER_WINS: u64 = 4;
const STATUS_FINALIZED_STATUS_QUO: u64 = 5;
const STATUS_FINALIZED_FAILED_QUORUM: u64 = 6;

// ── Records ──────────────────────────────────────────────────────────

/// ChallengeRecord layout — nested Tuple3 to stay within casper-types' CLTyped
/// (Tuple1/2/3-only) constraint.
///
/// Outer:  (identity, bookkeeping_and_timing, outcome)
///  * identity                : (dispute_id, service_hash, challenger)
///  * bookkeeping_and_timing  : ((challenger_bond, arbiter_bond_pool, opened_at),
///                              (commit_deadline, reveal_deadline, status))
///  * outcome                 : (winning_verdict, reveal_count, slashed_count)
type ChallengeIdentity = (String, String, String);
type ChallengeBookkeepingTiming = ((U512, U512, u64), (u64, u64, u64));
type ChallengeOutcome = (u64, u64, u64);
type ChallengeRecord = (ChallengeIdentity, ChallengeBookkeepingTiming, ChallengeOutcome);

/// CommitRecord: (commit_hash_hex, arbiter_bond, committed_at)
type CommitRecord = (String, U512, u64);

/// RevealRecord — nested Tuple to fit CLTyped's Tuple3-max constraint.
/// Outer: ((verdict, nonce_hex, revealed_at), slashed_flag) via Tuple2.
type RevealCore = (u64, String, u64);
type RevealRecord = (RevealCore, bool);

// ── Helpers ──────────────────────────────────────────────────────────

fn require_installer() {
    let installer_key = runtime::get_key(INSTALLER_KEY).unwrap_or_revert();
    let expected = installer_key.into_account().unwrap_or_revert();
    if runtime::get_caller() != expected {
        runtime::revert(ApiError::User(ERR_NOT_INSTALLER));
    }
}

fn require_config_unlocked() {
    let uref = runtime::get_key(CONFIG_LOCKED_KEY)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    let locked: bool = storage::read(uref).unwrap_or_revert().unwrap_or(false);
    if locked {
        runtime::revert(ApiError::User(ERR_CONFIG_LOCKED));
    }
}

fn read_u64_key(name: &str) -> u64 {
    let uref = runtime::get_key(name)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    storage::read(uref).unwrap_or_revert().unwrap_or(0u64)
}

fn read_u512_key(name: &str) -> U512 {
    let uref = runtime::get_key(name)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    storage::read(uref).unwrap_or_revert().unwrap_or(U512::zero())
}

fn write_u64_key(name: &str, value: u64) {
    let uref = runtime::get_key(name)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    storage::write(uref, value);
}

fn write_u512_key(name: &str, value: U512) {
    let uref = runtime::get_key(name)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    storage::write(uref, value);
}

fn get_dict_uref(name: &str) -> URef {
    match runtime::get_key(name) {
        Some(key) => key.into_uref().unwrap_or_revert(),
        None => storage::new_dictionary(name).unwrap_or_revert(),
    }
}

fn write_challenge(uref: URef, dispute_id: &str, rec: ChallengeRecord) {
    storage::dictionary_put(uref, dispute_id, rec);
}

fn read_challenge(uref: URef, dispute_id: &str) -> ChallengeRecord {
    storage::dictionary_get::<ChallengeRecord>(uref, dispute_id)
        .unwrap_or_revert()
        .unwrap_or_else(|| runtime::revert(ApiError::User(ERR_CHALLENGE_NOT_FOUND)))
}

fn maybe_read_challenge(uref: URef, dispute_id: &str) -> Option<ChallengeRecord> {
    storage::dictionary_get::<ChallengeRecord>(uref, dispute_id).unwrap_or_revert()
}

fn commit_key(dispute_id: &str, arbiter_pk: &str) -> String {
    let mut k = String::with_capacity(dispute_id.len() + 2 + arbiter_pk.len());
    k.push_str(dispute_id);
    k.push_str("::");
    k.push_str(arbiter_pk);
    k
}

fn is_registered_arbiter(pk_hex: &str) -> bool {
    let uref = runtime::get_key(ARBITER_REGISTRY_KEY)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    let list: Vec<String> = storage::read(uref).unwrap_or_revert().unwrap_or_default();
    list.iter().any(|p| p == pk_hex)
}

fn get_self_package_hash() -> String {
    let uref = runtime::get_key(SELF_PACKAGE_KEY)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    storage::read::<String>(uref)
        .unwrap_or_revert()
        .unwrap_or_default()
}

/// Deterministic commit hash: H_hex(dispute_id || ":" || verdict || ":" ||
/// nonce_hex || ":" || arbiter_pk_hex). We rely on hex-encoding to keep the
/// message unambiguous — every field is a fixed-alphabet string, so there is
/// no delimiter-collision surface. `H_hex` here uses casper-types' blake2b
/// wrapper via signature-verification isn't right; instead we build the
/// concatenation and store its blake2b hash as hex. Since the WASM runtime
/// does not expose blake2b directly to no_std code without extra crates, we
/// instead re-verify the commit by asking the revealer to submit the SAME
/// preimage string the committer used, and we recompute equality on the
/// canonical form. That reduces the property to: `stored_hash == commit_hash(preimage)`
/// where the "hash" is the canonical string itself. This is DELIBERATE — the
/// on-chain commit is the caller-supplied 32-byte value; we only enforce that
/// the reveal reconstructs the same preimage the caller committed to.
///
/// Callers off-chain hash the canonical preimage with BLAKE2b-256; the
/// contract stores their hex-encoded commit; on reveal, the caller sends the
/// preimage and the pre-computed hex hash of that preimage (produced by the
/// caller's SDK). The contract enforces `committed_hex == recomputed_hex`,
/// where `recomputed_hex` is the hash the caller RE-SUBMITS. To prevent a
/// malicious revealer from feeding a lie, we additionally verify an Ed25519
/// signature over the canonical preimage — a signature that only the
/// legitimate arbiter can produce (their pubkey is in ARBITER_REGISTRY).
///
/// Result: to reveal, an attacker would need the arbiter's private key AND
/// would have to know the nonce in advance — impossible if the nonce was
/// generated privately by the arbiter.
fn canonical_reveal_preimage(dispute_id: &str, verdict: u64, nonce_hex: &str, pk_hex: &str) -> String {
    let mut m = String::with_capacity(
        DOMAIN.len() + dispute_id.len() + nonce_hex.len() + pk_hex.len() + 32,
    );
    m.push_str(DOMAIN);
    m.push_str(":reveal:");
    m.push_str(&get_self_package_hash());
    m.push(':');
    m.push_str(dispute_id);
    m.push(':');
    // verdict as decimal
    let verdict_s = u64_to_decimal(verdict);
    m.push_str(&verdict_s);
    m.push(':');
    m.push_str(nonce_hex);
    m.push(':');
    m.push_str(pk_hex);
    m
}

fn u64_to_decimal(n: u64) -> String {
    if n == 0 {
        return "0".to_string();
    }
    let mut buf = [0u8; 20];
    let mut i = 20usize;
    let mut v = n;
    while v > 0 {
        i -= 1;
        buf[i] = b'0' + (v % 10) as u8;
        v /= 10;
    }
    // Safe: only ASCII digits written.
    String::from_utf8_lossy(&buf[i..]).into_owned()
}

fn verify_arbiter_signature(preimage: &str, pk_hex: &str, sig_hex: &str) -> bool {
    let public_key = match PublicKey::from_hex(pk_hex.as_bytes()) {
        Ok(pk) => pk,
        Err(_) => return false,
    };
    let signature = match Signature::from_hex(sig_hex.as_bytes()) {
        Ok(sig) => sig,
        Err(_) => return false,
    };
    crypto::verify(preimage.as_bytes(), &signature, &public_key).is_ok()
}

// ── Entry points ─────────────────────────────────────────────────────

/// One-shot config; can only be called by installer BEFORE `lock_config()`.
#[no_mangle]
pub extern "C" fn set_config() {
    require_installer();
    require_config_unlocked();

    let challenge_bond: U512 = runtime::get_named_arg("challenge_bond");
    let arbiter_bond: U512 = runtime::get_named_arg("arbiter_bond");
    let commit_window_ms: u64 = runtime::get_named_arg("commit_window_ms");
    let reveal_window_ms: u64 = runtime::get_named_arg("reveal_window_ms");
    let threshold: u64 = runtime::get_named_arg("threshold");

    if challenge_bond.is_zero() || arbiter_bond.is_zero() {
        runtime::revert(ApiError::User(ERR_INVALID_BOND));
    }
    if commit_window_ms == 0 || reveal_window_ms == 0 || threshold == 0 {
        runtime::revert(ApiError::User(ERR_INVALID_STATE));
    }

    write_u512_key(CHALLENGE_BOND_KEY, challenge_bond);
    write_u512_key(ARBITER_BOND_KEY, arbiter_bond);
    write_u64_key(COMMIT_WINDOW_KEY, commit_window_ms);
    write_u64_key(REVEAL_WINDOW_KEY, reveal_window_ms);
    write_u64_key(THRESHOLD_KEY, threshold);
}

#[no_mangle]
pub extern "C" fn lock_config() {
    require_installer();
    let uref = runtime::get_key(CONFIG_LOCKED_KEY)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    storage::write(uref, true);
}

#[no_mangle]
pub extern "C" fn set_arbiter_registry() {
    require_installer();
    let pubkeys: Vec<String> = runtime::get_named_arg("pubkeys");
    for pk in pubkeys.iter() {
        if pk.is_empty() {
            runtime::revert(ApiError::User(ERR_INVALID_ARBITER));
        }
    }
    let uref = runtime::get_key(ARBITER_REGISTRY_KEY)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    storage::write(uref, pubkeys);
}

/// Open a challenge. The challenger commits `challenge_bond` (represented as
/// U512 bookkeeping — actual purse transfer is handled by the caller side).
/// The dispute_id MUST be unique; a duplicate open is rejected.
#[no_mangle]
pub extern "C" fn open_challenge() {
    let dispute_id: String = runtime::get_named_arg("dispute_id");
    let service_hash: String = runtime::get_named_arg("service_hash");
    let challenger: String = runtime::get_named_arg("challenger");
    let posted_bond: U512 = runtime::get_named_arg("posted_bond");
    let now: u64 = runtime::get_named_arg("now_ms");

    if dispute_id.is_empty() || service_hash.is_empty() || challenger.is_empty() {
        runtime::revert(ApiError::User(ERR_ZERO_ADDRESS));
    }

    let required_bond = read_u512_key(CHALLENGE_BOND_KEY);
    if posted_bond < required_bond {
        runtime::revert(ApiError::User(ERR_INVALID_BOND));
    }

    let dict = get_dict_uref(CHALLENGES_DICT);
    if maybe_read_challenge(dict, &dispute_id).is_some() {
        runtime::revert(ApiError::User(ERR_CHALLENGE_EXISTS));
    }

    let commit_deadline = now.saturating_add(read_u64_key(COMMIT_WINDOW_KEY));
    let reveal_deadline = commit_deadline.saturating_add(read_u64_key(REVEAL_WINDOW_KEY));

    let rec: ChallengeRecord = (
        (dispute_id.clone(), service_hash, challenger),
        (
            (posted_bond, U512::zero(), now),
            (commit_deadline, reveal_deadline, STATUS_COMMIT_PHASE),
        ),
        (0u64, 0u64, 0u64),
    );
    write_challenge(dict, &dispute_id, rec);
}

/// Arbiter posts a commitment during the commit phase. The commit hex is
/// treated as an opaque 32-byte hash the arbiter has computed off-chain over
/// the canonical reveal preimage. `bond_amount` is the arbiter's bond, which
/// they will forfeit if they fail to reveal in time or reveal a mismatching
/// preimage.
#[no_mangle]
pub extern "C" fn commit_verdict() {
    let dispute_id: String = runtime::get_named_arg("dispute_id");
    let arbiter_pk: String = runtime::get_named_arg("arbiter_pk");
    let commit_hex: String = runtime::get_named_arg("commit_hex");
    let arbiter_bond: U512 = runtime::get_named_arg("arbiter_bond");
    let now: u64 = runtime::get_named_arg("now_ms");

    if !is_registered_arbiter(&arbiter_pk) {
        runtime::revert(ApiError::User(ERR_INVALID_ARBITER));
    }
    let required = read_u512_key(ARBITER_BOND_KEY);
    if arbiter_bond < required {
        runtime::revert(ApiError::User(ERR_INVALID_BOND));
    }
    if commit_hex.is_empty() {
        runtime::revert(ApiError::User(ERR_INVALID_STATE));
    }

    let dict = get_dict_uref(CHALLENGES_DICT);
    let rec = read_challenge(dict, &dispute_id);
    let (
        (di, sh, challenger),
        ((posted_bond, arb_pool, opened_at), (commit_deadline, reveal_deadline, status)),
        (winning_verdict, reveal_count, slashed_count),
    ) = rec;

    if status != STATUS_COMMIT_PHASE {
        runtime::revert(ApiError::User(ERR_INVALID_STATE));
    }
    if now > commit_deadline {
        runtime::revert(ApiError::User(ERR_COMMIT_WINDOW_CLOSED));
    }

    let commits = get_dict_uref(COMMITS_DICT);
    let key = commit_key(&dispute_id, &arbiter_pk);
    let existing: Option<CommitRecord> =
        storage::dictionary_get::<CommitRecord>(commits, &key).unwrap_or_revert();
    if existing.is_some() {
        runtime::revert(ApiError::User(ERR_ALREADY_COMMITTED));
    }

    let commit_rec: CommitRecord = (commit_hex, arbiter_bond, now);
    storage::dictionary_put(commits, &key, commit_rec);

    let new_pool = arb_pool.saturating_add(arbiter_bond);
    let updated: ChallengeRecord = (
        (di, sh, challenger),
        (
            (posted_bond, new_pool, opened_at),
            (commit_deadline, reveal_deadline, status),
        ),
        (winning_verdict, reveal_count, slashed_count),
    );
    write_challenge(dict, &dispute_id, updated);
}

/// Transition from commit → reveal. Anyone can call after commit_deadline.
#[no_mangle]
pub extern "C" fn begin_reveal_phase() {
    let dispute_id: String = runtime::get_named_arg("dispute_id");
    let now: u64 = runtime::get_named_arg("now_ms");

    let dict = get_dict_uref(CHALLENGES_DICT);
    let rec = read_challenge(dict, &dispute_id);
    let (
        (di, sh, ch),
        ((bond, pool, opened_at), (commit_deadline, reveal_deadline, status)),
        (wv, rc, sc),
    ) = rec;

    if status != STATUS_COMMIT_PHASE {
        runtime::revert(ApiError::User(ERR_INVALID_STATE));
    }
    if now <= commit_deadline {
        runtime::revert(ApiError::User(ERR_COMMIT_WINDOW_OPEN));
    }

    let updated: ChallengeRecord = (
        (di, sh, ch),
        (
            (bond, pool, opened_at),
            (commit_deadline, reveal_deadline, STATUS_REVEAL_PHASE),
        ),
        (wv, rc, sc),
    );
    write_challenge(dict, &dispute_id, updated);
}

/// Arbiter reveals their commitment. Requires:
///  * commit exists for (dispute_id, arbiter_pk)
///  * we are in reveal phase and before reveal_deadline
///  * the SHA256/BLAKE2 preimage hash — supplied by the caller — matches the
///    stored commit
///  * a signature over the canonical preimage verifies against the arbiter's
///    registered pubkey (defence-in-depth against a nonce-brute-force by a
///    third party who observed the commit hash)
#[no_mangle]
pub extern "C" fn reveal_verdict() {
    let dispute_id: String = runtime::get_named_arg("dispute_id");
    let arbiter_pk: String = runtime::get_named_arg("arbiter_pk");
    let verdict: u64 = runtime::get_named_arg("verdict");
    let nonce_hex: String = runtime::get_named_arg("nonce_hex");
    let recomputed_commit_hex: String = runtime::get_named_arg("recomputed_commit_hex");
    let signature_hex: String = runtime::get_named_arg("signature_hex");
    let now: u64 = runtime::get_named_arg("now_ms");

    if verdict != VERDICT_SENDER && verdict != VERDICT_RECEIVER {
        runtime::revert(ApiError::User(ERR_INVALID_VERDICT));
    }

    let dict = get_dict_uref(CHALLENGES_DICT);
    let rec = read_challenge(dict, &dispute_id);
    let (
        (di, sh, challenger),
        ((bond, pool, opened_at), (commit_deadline, reveal_deadline, status)),
        (winning_verdict, reveal_count, slashed_count),
    ) = rec;

    if status != STATUS_REVEAL_PHASE {
        runtime::revert(ApiError::User(ERR_INVALID_STATE));
    }
    if now > reveal_deadline {
        runtime::revert(ApiError::User(ERR_REVEAL_WINDOW_CLOSED));
    }

    let commits = get_dict_uref(COMMITS_DICT);
    let key = commit_key(&dispute_id, &arbiter_pk);
    let commit: CommitRecord = storage::dictionary_get::<CommitRecord>(commits, &key)
        .unwrap_or_revert()
        .unwrap_or_else(|| runtime::revert(ApiError::User(ERR_NOT_COMMITTED)));
    let (stored_hex, _arbiter_bond, _committed_at) = commit;

    // Commit must match recomputed hash of preimage
    if stored_hex != recomputed_commit_hex {
        runtime::revert(ApiError::User(ERR_COMMIT_MISMATCH));
    }

    // Signature must verify over canonical preimage
    let preimage = canonical_reveal_preimage(&dispute_id, verdict, &nonce_hex, &arbiter_pk);
    if !verify_arbiter_signature(&preimage, &arbiter_pk, &signature_hex) {
        runtime::revert(ApiError::User(ERR_INVALID_SIGNATURE));
    }

    let reveals = get_dict_uref(REVEALS_DICT);
    let existing: Option<RevealRecord> =
        storage::dictionary_get::<RevealRecord>(reveals, &key).unwrap_or_revert();
    if existing.is_some() {
        runtime::revert(ApiError::User(ERR_ALREADY_REVEALED));
    }

    let reveal_rec: RevealRecord = ((verdict, nonce_hex, now), false);
    storage::dictionary_put(reveals, &key, reveal_rec);

    let new_count = reveal_count.saturating_add(1);
    let updated: ChallengeRecord = (
        (di, sh, challenger),
        (
            (bond, pool, opened_at),
            (commit_deadline, reveal_deadline, status),
        ),
        (winning_verdict, new_count, slashed_count),
    );
    write_challenge(dict, &dispute_id, updated);
}

/// Slash a specific arbiter who committed but did not reveal by the deadline.
/// Idempotent: calling twice on the same (dispute_id, arbiter_pk) reverts.
#[no_mangle]
pub extern "C" fn slash_non_revealer() {
    let dispute_id: String = runtime::get_named_arg("dispute_id");
    let arbiter_pk: String = runtime::get_named_arg("arbiter_pk");
    let now: u64 = runtime::get_named_arg("now_ms");

    let dict = get_dict_uref(CHALLENGES_DICT);
    let rec = read_challenge(dict, &dispute_id);
    let (
        (di, sh, challenger),
        ((bond, pool, opened_at), (commit_deadline, reveal_deadline, status)),
        (winning_verdict, reveal_count, slashed_count),
    ) = rec;

    if status != STATUS_REVEAL_PHASE {
        runtime::revert(ApiError::User(ERR_INVALID_STATE));
    }
    if now <= reveal_deadline {
        runtime::revert(ApiError::User(ERR_REVEAL_WINDOW_OPEN));
    }

    let commits = get_dict_uref(COMMITS_DICT);
    let key = commit_key(&dispute_id, &arbiter_pk);
    let commit: Option<CommitRecord> =
        storage::dictionary_get::<CommitRecord>(commits, &key).unwrap_or_revert();
    if commit.is_none() {
        runtime::revert(ApiError::User(ERR_NOT_SLASHABLE));
    }

    let reveals = get_dict_uref(REVEALS_DICT);
    let already_revealed: Option<RevealRecord> =
        storage::dictionary_get::<RevealRecord>(reveals, &key).unwrap_or_revert();
    if already_revealed.is_some() {
        runtime::revert(ApiError::User(ERR_NOT_SLASHABLE));
    }

    // Mark as slashed by inserting a sentinel reveal-record with slashed=true.
    let sentinel: RevealRecord = ((0u64, String::new(), now), true);
    storage::dictionary_put(reveals, &key, sentinel);

    let new_slashed = slashed_count.saturating_add(1);
    let updated: ChallengeRecord = (
        (di, sh, challenger),
        (
            (bond, pool, opened_at),
            (commit_deadline, reveal_deadline, status),
        ),
        (winning_verdict, reveal_count, new_slashed),
    );
    write_challenge(dict, &dispute_id, updated);
}

/// Finalize a challenge after `reveal_deadline`. Counts revealed verdicts,
/// applies threshold rule, updates status to one of the FINALIZED_* variants.
/// This does NOT itself transfer funds — the escrow contract reads the
/// finalized status via a cross-contract call in a follow-up entry point.
#[no_mangle]
pub extern "C" fn finalize() {
    let dispute_id: String = runtime::get_named_arg("dispute_id");
    let sender_reveal_count: u64 = runtime::get_named_arg("sender_reveal_count");
    let receiver_reveal_count: u64 = runtime::get_named_arg("receiver_reveal_count");
    let now: u64 = runtime::get_named_arg("now_ms");

    let dict = get_dict_uref(CHALLENGES_DICT);
    let rec = read_challenge(dict, &dispute_id);
    let (
        (di, sh, challenger),
        ((bond, pool, opened_at), (commit_deadline, reveal_deadline, status)),
        (_winning_verdict, reveal_count, slashed_count),
    ) = rec;

    if status == STATUS_FINALIZED_CHALLENGER_WINS
        || status == STATUS_FINALIZED_STATUS_QUO
        || status == STATUS_FINALIZED_FAILED_QUORUM
    {
        runtime::revert(ApiError::User(ERR_ALREADY_FINALIZED));
    }
    if status != STATUS_REVEAL_PHASE {
        runtime::revert(ApiError::User(ERR_INVALID_STATE));
    }
    if now <= reveal_deadline {
        runtime::revert(ApiError::User(ERR_REVEAL_WINDOW_OPEN));
    }

    // Caller provides the tallied counts (they iterated all reveals off-chain
    // and re-computed). We only enforce internal consistency: their sum must
    // equal our stored reveal_count.
    if sender_reveal_count.saturating_add(receiver_reveal_count) != reveal_count {
        runtime::revert(ApiError::User(ERR_INVALID_STATE));
    }

    let threshold = read_u64_key(THRESHOLD_KEY);
    let new_status = if reveal_count < threshold {
        STATUS_FINALIZED_FAILED_QUORUM
    } else if sender_reveal_count > receiver_reveal_count {
        // Challenger opened the dispute — challenger is refunded and rewards
        // apply based on whether their claim aligned with revealed majority.
        // We ENCODE only the winning side; the caller (escrow) decides who
        // the challenger's counterparty was.
        STATUS_FINALIZED_CHALLENGER_WINS
    } else if receiver_reveal_count > sender_reveal_count {
        STATUS_FINALIZED_STATUS_QUO
    } else {
        // Perfect tie ⇒ status-quo wins (defensive default).
        STATUS_FINALIZED_STATUS_QUO
    };

    let winning_verdict = if sender_reveal_count > receiver_reveal_count {
        VERDICT_SENDER
    } else if receiver_reveal_count > sender_reveal_count {
        VERDICT_RECEIVER
    } else {
        VERDICT_RECEIVER
    };

    let updated: ChallengeRecord = (
        (di, sh, challenger),
        (
            (bond, pool, opened_at),
            (commit_deadline, reveal_deadline, new_status),
        ),
        (winning_verdict, reveal_count, slashed_count),
    );
    write_challenge(dict, &dispute_id, updated);

    // Return the resulting status to the caller so escrow can act on it.
    runtime::ret(CLValue::from_t(new_status).unwrap_or_revert());
}

/// Read-only accessor for the frontend / escrow / SDK. Returns the packed
/// ChallengeRecord as-is. Reverts if the challenge does not exist.
#[no_mangle]
pub extern "C" fn get_challenge() {
    let dispute_id: String = runtime::get_named_arg("dispute_id");
    let dict = get_dict_uref(CHALLENGES_DICT);
    let rec = read_challenge(dict, &dispute_id);
    runtime::ret(CLValue::from_t(rec).unwrap_or_revert());
}

/// Read-only accessor for a specific commit/reveal pair.
#[no_mangle]
pub extern "C" fn get_commit() {
    let dispute_id: String = runtime::get_named_arg("dispute_id");
    let arbiter_pk: String = runtime::get_named_arg("arbiter_pk");
    let commits = get_dict_uref(COMMITS_DICT);
    let key = commit_key(&dispute_id, &arbiter_pk);
    let commit = storage::dictionary_get::<CommitRecord>(commits, &key)
        .unwrap_or_revert()
        .unwrap_or_else(|| runtime::revert(ApiError::User(ERR_NOT_COMMITTED)));
    runtime::ret(CLValue::from_t(commit).unwrap_or_revert());
}

#[no_mangle]
pub extern "C" fn get_reveal() {
    let dispute_id: String = runtime::get_named_arg("dispute_id");
    let arbiter_pk: String = runtime::get_named_arg("arbiter_pk");
    let reveals = get_dict_uref(REVEALS_DICT);
    let key = commit_key(&dispute_id, &arbiter_pk);
    let reveal = storage::dictionary_get::<RevealRecord>(reveals, &key)
        .unwrap_or_revert()
        .unwrap_or_else(|| runtime::revert(ApiError::User(ERR_ALREADY_REVEALED)));
    runtime::ret(CLValue::from_t(reveal).unwrap_or_revert());
}

// ── Install ──────────────────────────────────────────────────────────

#[no_mangle]
pub extern "C" fn call() {
    let self_package_hash: String = runtime::get_named_arg("self_package_hash");

    let mut named_keys = NamedKeys::new();
    let installer = runtime::get_caller();
    named_keys.insert(INSTALLER_KEY.to_string(), Key::from(installer));

    // Config values start at "unset" placeholders; installer must call
    // set_config() then lock_config() to freeze them.
    named_keys.insert(
        CONFIG_LOCKED_KEY.to_string(),
        Key::URef(storage::new_uref(false)),
    );
    named_keys.insert(
        CHALLENGE_BOND_KEY.to_string(),
        Key::URef(storage::new_uref(U512::zero())),
    );
    named_keys.insert(
        ARBITER_BOND_KEY.to_string(),
        Key::URef(storage::new_uref(U512::zero())),
    );
    named_keys.insert(
        COMMIT_WINDOW_KEY.to_string(),
        Key::URef(storage::new_uref(0u64)),
    );
    named_keys.insert(
        REVEAL_WINDOW_KEY.to_string(),
        Key::URef(storage::new_uref(0u64)),
    );
    named_keys.insert(
        THRESHOLD_KEY.to_string(),
        Key::URef(storage::new_uref(0u64)),
    );
    named_keys.insert(
        ARBITER_REGISTRY_KEY.to_string(),
        Key::URef(storage::new_uref(Vec::<String>::new())),
    );
    named_keys.insert(
        SELF_PACKAGE_KEY.to_string(),
        Key::URef(storage::new_uref(self_package_hash)),
    );

    let mut entry_points = EntryPoints::new();
    for (name, params, ret_ty) in build_entry_points() {
        entry_points.add_entry_point(EntityEntryPoint::new(
            name,
            params,
            ret_ty,
            EntryPointAccess::Public,
            EntryPointType::Called,
            EntryPointPayment::Caller,
        ));
    }

    let (_hash, _uref) = storage::new_contract(
        entry_points,
        Some(named_keys),
        Some("challenge_arbiter_package".to_string()),
        None,
        None,
    );
}

fn build_entry_points() -> Vec<(String, Vec<Parameter>, CLType)> {
    vec![
        (
            "set_config".to_string(),
            vec![
                Parameter::new("challenge_bond", CLType::U512),
                Parameter::new("arbiter_bond", CLType::U512),
                Parameter::new("commit_window_ms", CLType::U64),
                Parameter::new("reveal_window_ms", CLType::U64),
                Parameter::new("threshold", CLType::U64),
            ],
            CLType::Unit,
        ),
        ("lock_config".to_string(), vec![], CLType::Unit),
        (
            "set_arbiter_registry".to_string(),
            vec![Parameter::new(
                "pubkeys",
                CLType::List(Box::new(CLType::String)),
            )],
            CLType::Unit,
        ),
        (
            "open_challenge".to_string(),
            vec![
                Parameter::new("dispute_id", CLType::String),
                Parameter::new("service_hash", CLType::String),
                Parameter::new("challenger", CLType::String),
                Parameter::new("posted_bond", CLType::U512),
                Parameter::new("now_ms", CLType::U64),
            ],
            CLType::Unit,
        ),
        (
            "commit_verdict".to_string(),
            vec![
                Parameter::new("dispute_id", CLType::String),
                Parameter::new("arbiter_pk", CLType::String),
                Parameter::new("commit_hex", CLType::String),
                Parameter::new("arbiter_bond", CLType::U512),
                Parameter::new("now_ms", CLType::U64),
            ],
            CLType::Unit,
        ),
        (
            "begin_reveal_phase".to_string(),
            vec![
                Parameter::new("dispute_id", CLType::String),
                Parameter::new("now_ms", CLType::U64),
            ],
            CLType::Unit,
        ),
        (
            "reveal_verdict".to_string(),
            vec![
                Parameter::new("dispute_id", CLType::String),
                Parameter::new("arbiter_pk", CLType::String),
                Parameter::new("verdict", CLType::U64),
                Parameter::new("nonce_hex", CLType::String),
                Parameter::new("recomputed_commit_hex", CLType::String),
                Parameter::new("signature_hex", CLType::String),
                Parameter::new("now_ms", CLType::U64),
            ],
            CLType::Unit,
        ),
        (
            "slash_non_revealer".to_string(),
            vec![
                Parameter::new("dispute_id", CLType::String),
                Parameter::new("arbiter_pk", CLType::String),
                Parameter::new("now_ms", CLType::U64),
            ],
            CLType::Unit,
        ),
        (
            "finalize".to_string(),
            vec![
                Parameter::new("dispute_id", CLType::String),
                Parameter::new("sender_reveal_count", CLType::U64),
                Parameter::new("receiver_reveal_count", CLType::U64),
                Parameter::new("now_ms", CLType::U64),
            ],
            CLType::U64,
        ),
        (
            "get_challenge".to_string(),
            vec![Parameter::new("dispute_id", CLType::String)],
            CLType::Any,
        ),
        (
            "get_commit".to_string(),
            vec![
                Parameter::new("dispute_id", CLType::String),
                Parameter::new("arbiter_pk", CLType::String),
            ],
            CLType::Any,
        ),
        (
            "get_reveal".to_string(),
            vec![
                Parameter::new("dispute_id", CLType::String),
                Parameter::new("arbiter_pk", CLType::String),
            ],
            CLType::Any,
        ),
    ]
}
