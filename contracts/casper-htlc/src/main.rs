#![no_std]
#![no_main]

//! Casper HTLC — the missing counterpart to `contracts/HTLC.sol`.
//!
//! Byte-for-byte state machine mirror of `server/bridge_htlc.py` and
//! `contracts/HTLC.sol` on the EVM leg:
//!
//!     EMPTY -> LOCKED -> CLAIMED | REFUNDED
//!
//! Uses **sha256** for the hashlock (not blake2b) so the same
//! `(preimage, hashlock)` pair works on both legs of a cross-chain
//! atomic swap without adapter re-hashing.
//!
//! Entry points:
//!   - `lock(hashlock_hex: String, timelock: u64, receiver: AccountHash,
//!           source_purse: URef, amount: U512)` — creates a new HTLC.
//!   - `claim(hashlock_hex: String, preimage: Vec<u8>)` — releases funds
//!     to `receiver` if `sha256(preimage) == hashlock` AND `now < timelock`.
//!   - `refund(hashlock_hex: String)` — returns funds to `sender` if
//!     `now >= timelock`.
//!   - `get_status(hashlock_hex: String) -> (u8, U512)` — returns
//!     (state, remaining_amount) for the given swap.
//!
//! State per swap is stored in a single dictionary keyed by
//! `hashlock_hex` (lowercase hex of the 32-byte sha256 output). The
//! record layout is a nested tuple so it can be round-tripped through
//! Casper's `CLValue` bytesrepr without a custom `ToBytes` impl:
//!
//!     ((sender_hex, receiver_hex, amount_str), (state, timelock))

extern crate alloc;

use alloc::string::{String, ToString};
use alloc::vec::Vec;

use casper_contract::contract_api::{runtime, storage, system};
use casper_contract::unwrap_or_revert::UnwrapOrRevert;
use casper_types::account::AccountHash;
use casper_types::contracts::NamedKeys;
use casper_types::{
    ApiError, CLType, CLValue, EntityEntryPoint, EntryPointAccess, EntryPointPayment,
    EntryPointType, EntryPoints, Parameter, URef, U512,
};

// ── Error codes ──────────────────────────────────────────────────────

const ERR_NOT_FOUND: u16 = 1;
const ERR_ALREADY_EXISTS: u16 = 2;
const ERR_PREIMAGE_MISMATCH: u16 = 3;
const ERR_TIMELOCK_NOT_EXPIRED: u16 = 4;
const ERR_TIMELOCK_EXPIRED: u16 = 5;
const ERR_NOT_LOCKED: u16 = 6;
const ERR_ZERO_AMOUNT: u16 = 7;
#[allow(dead_code)]
const ERR_UNAUTHORIZED: u16 = 8;
const ERR_INVALID_HASHLOCK: u16 = 9;
#[allow(dead_code)]
const ERR_INVALID_PREIMAGE: u16 = 10;

// ── Storage keys ─────────────────────────────────────────────────────

const LOCKS_DICT: &str = "htlc_locks";
const CONTRACT_PURSE: &str = "contract_purse";
const INSTALLER_KEY: &str = "installer";
const SWAP_COUNT_KEY: &str = "swap_count";

// ── State machine ────────────────────────────────────────────────────

const STATE_LOCKED: u8 = 1;
const STATE_CLAIMED: u8 = 2;
const STATE_REFUNDED: u8 = 3;

// A swap record: ((sender_hex, receiver_hex, amount_str), (state, timelock_ms))
type SwapRecord = ((String, String, String), (u8, u64));

// ── Helpers ──────────────────────────────────────────────────────────

fn get_dict_uref(name: &str) -> URef {
    // Casper 2.2.x (audit-082): new_dictionary is disallowed in session/install context.
    // Dicts and purses are lazily created inside entry points (Called context).
    match runtime::get_key(name) {
        Some(key) => key.into_uref().unwrap_or_revert(),
        None => storage::new_dictionary(name).unwrap_or_revert(),
    }
}

fn get_or_create_purse() -> URef {
    match runtime::get_key(CONTRACT_PURSE) {
        Some(key) => key.into_uref().unwrap_or_revert(),
        None => {
            let purse = system::create_purse();
            runtime::put_key(CONTRACT_PURSE, purse.into());
            purse
        }
    }
}

fn read_swap(dict: URef, key: &str) -> SwapRecord {
    storage::dictionary_get::<SwapRecord>(dict, key)
        .unwrap_or_revert()
        .unwrap_or_revert_with(ApiError::User(ERR_NOT_FOUND))
}

fn try_read_swap(dict: URef, key: &str) -> Option<SwapRecord> {
    storage::dictionary_get::<SwapRecord>(dict, key)
        .unwrap_or_revert()
}

fn write_swap(dict: URef, key: &str, record: SwapRecord) {
    storage::dictionary_put(dict, key, record);
}

fn parse_u512(s: &str) -> U512 {
    match U512::from_dec_str(s) {
        Ok(v) => v,
        Err(_) => runtime::revert(ApiError::User(ERR_INVALID_HASHLOCK)),
    }
}

fn hex_decode_32(s: &str) -> [u8; 32] {
    if s.len() != 64 {
        runtime::revert(ApiError::User(ERR_INVALID_HASHLOCK));
    }
    let mut out = [0u8; 32];
    for (i, chunk) in s.as_bytes().chunks(2).enumerate() {
        if i >= 32 {
            break;
        }
        let hi = (chunk[0] as char)
            .to_digit(16)
            .unwrap_or_revert_with(ApiError::User(ERR_INVALID_HASHLOCK)) as u8;
        let lo = (chunk[1] as char)
            .to_digit(16)
            .unwrap_or_revert_with(ApiError::User(ERR_INVALID_HASHLOCK)) as u8;
        out[i] = (hi << 4) | lo;
    }
    out
}

fn hex_encode(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        out.push(HEX[(b >> 4) as usize] as char);
        out.push(HEX[(b & 0x0f) as usize] as char);
    }
    out
}

fn sha256_bytes(preimage: &[u8]) -> [u8; 32] {
    use sha2::{Digest, Sha256};
    Sha256::digest(preimage).into()
}

fn account_hash_hex(a: &AccountHash) -> String {
    hex_encode(a.as_bytes())
}

fn parse_account(s: &str) -> AccountHash {
    match AccountHash::from_formatted_str(s) {
        Ok(v) => v,
        Err(_) => AccountHash::new(hex_decode_32(s)),
    }
}

// ── Entry points ─────────────────────────────────────────────────────

/// Lock CSPR under a sha256 hashlock. Only the `receiver` can claim
/// (with preimage) before `timelock_ms`; after that only the `sender`
/// (implicit — refund puts funds back to `sender`) via `refund()`.
///
/// - `hashlock_hex`: lowercase hex of sha256(preimage), exactly 64 chars
/// - `timelock_ms`: absolute unix time in **milliseconds** at/after which
///   claim is rejected and refund becomes possible. Milliseconds match
///   the mock (`bridge_htlc.py`) and `HTLC.sol`.
/// - `receiver`: AccountHash of who can claim
/// - `source_purse`: caller's purse to draw `amount` from
/// - `amount`: motes to lock (must be > 0)
#[no_mangle]
pub extern "C" fn lock() {
    let sender = runtime::get_caller();
    let hashlock_hex: String = runtime::get_named_arg("hashlock_hex");
    let timelock_ms: u64 = runtime::get_named_arg("timelock_ms");
    let receiver: AccountHash = runtime::get_named_arg("receiver");
    let source_purse: URef = runtime::get_named_arg("source_purse");
    let amount: U512 = runtime::get_named_arg("amount");

    if amount.is_zero() {
        runtime::revert(ApiError::User(ERR_ZERO_AMOUNT));
    }
    // Validate hashlock format eagerly.
    let _ = hex_decode_32(&hashlock_hex);

    let dict = get_dict_uref(LOCKS_DICT);
    if try_read_swap(dict, &hashlock_hex).is_some() {
        runtime::revert(ApiError::User(ERR_ALREADY_EXISTS));
    }

    // Checks-effects-interactions: write the LOCKED record BEFORE the
    // transfer_from_purse_to_purse call, since the transfer is the only
    // side-effect that could trigger a reentry-style callback in a
    // future host upgrade.
    let record: SwapRecord = (
        (
            account_hash_hex(&sender),
            account_hash_hex(&receiver),
            amount.to_string(),
        ),
        (STATE_LOCKED, timelock_ms),
    );
    write_swap(dict, &hashlock_hex, record);

    let contract_purse = get_or_create_purse();
    system::transfer_from_purse_to_purse(source_purse, contract_purse, amount, None)
        .unwrap_or_revert();

    runtime::ret(CLValue::from_t(hashlock_hex).unwrap_or_revert());
}

/// Reveal the preimage and pull the locked funds to the receiver.
/// Rejects with:
///   - ERR_NOT_LOCKED if the swap isn't LOCKED (missing, already terminal)
///   - ERR_TIMELOCK_EXPIRED if `now >= timelock_ms`
///   - ERR_PREIMAGE_MISMATCH if `sha256(preimage) != hashlock`
#[no_mangle]
pub extern "C" fn claim() {
    let hashlock_hex: String = runtime::get_named_arg("hashlock_hex");
    let preimage: Vec<u8> = runtime::get_named_arg("preimage");

    let dict = get_dict_uref(LOCKS_DICT);
    let ((sender_str, receiver_str, amount_str), (state, timelock_ms)) =
        read_swap(dict, &hashlock_hex);

    if state != STATE_LOCKED {
        runtime::revert(ApiError::User(ERR_NOT_LOCKED));
    }

    let now_ms: u64 = u64::from(runtime::get_blocktime());
    if now_ms >= timelock_ms {
        runtime::revert(ApiError::User(ERR_TIMELOCK_EXPIRED));
    }

    let computed = sha256_bytes(&preimage);
    let computed_hex = hex_encode(&computed);
    if computed_hex != hashlock_hex {
        runtime::revert(ApiError::User(ERR_PREIMAGE_MISMATCH));
    }

    let amount = parse_u512(&amount_str);

    // C-E-I: mark CLAIMED before transferring out.
    let updated: SwapRecord = (
        (sender_str, receiver_str.clone(), amount_str),
        (STATE_CLAIMED, timelock_ms),
    );
    write_swap(dict, &hashlock_hex, updated);

    let receiver = parse_account(&receiver_str);
    let contract_purse = get_or_create_purse();
    system::transfer_from_purse_to_account(contract_purse, receiver, amount, None)
        .unwrap_or_revert();
}

/// Return funds to sender after timelock expires. Rejects with:
///   - ERR_NOT_LOCKED if the swap isn't LOCKED
///   - ERR_TIMELOCK_NOT_EXPIRED if `now < timelock_ms`
#[no_mangle]
pub extern "C" fn refund() {
    let hashlock_hex: String = runtime::get_named_arg("hashlock_hex");

    let dict = get_dict_uref(LOCKS_DICT);
    let ((sender_str, receiver_str, amount_str), (state, timelock_ms)) =
        read_swap(dict, &hashlock_hex);

    if state != STATE_LOCKED {
        runtime::revert(ApiError::User(ERR_NOT_LOCKED));
    }

    let now_ms: u64 = u64::from(runtime::get_blocktime());
    if now_ms < timelock_ms {
        runtime::revert(ApiError::User(ERR_TIMELOCK_NOT_EXPIRED));
    }

    let amount = parse_u512(&amount_str);

    // C-E-I: mark REFUNDED before transferring out.
    let updated: SwapRecord = (
        (sender_str.clone(), receiver_str, amount_str),
        (STATE_REFUNDED, timelock_ms),
    );
    write_swap(dict, &hashlock_hex, updated);

    let sender = parse_account(&sender_str);
    let contract_purse = get_or_create_purse();
    system::transfer_from_purse_to_account(contract_purse, sender, amount, None)
        .unwrap_or_revert();
}

/// Read-only query: `(state, remaining_amount)` for `hashlock_hex`.
/// State is 0 for missing (EMPTY), 1 LOCKED, 2 CLAIMED, 3 REFUNDED.
#[no_mangle]
pub extern "C" fn get_status() {
    let hashlock_hex: String = runtime::get_named_arg("hashlock_hex");
    let dict = get_dict_uref(LOCKS_DICT);

    let (state, amount) = match try_read_swap(dict, &hashlock_hex) {
        None => (0u8, U512::zero()),
        Some(((_, _, amount_str), (state, _))) => {
            if state == STATE_LOCKED {
                (state, parse_u512(&amount_str))
            } else {
                (state, U512::zero())
            }
        }
    };
    let out: (u8, U512) = (state, amount);
    runtime::ret(CLValue::from_t(out).unwrap_or_revert());
}

// ── Installer ────────────────────────────────────────────────────────

#[no_mangle]
pub extern "C" fn call() {
    let mut entry_points = EntryPoints::new();

    entry_points.add_entry_point(EntityEntryPoint::new(
        "lock",
        alloc::vec![
            Parameter::new("hashlock_hex", CLType::String),
            Parameter::new("timelock_ms", CLType::U64),
            Parameter::new("receiver", CLType::ByteArray(32)),
            Parameter::new("source_purse", CLType::URef),
            Parameter::new("amount", CLType::U512),
        ],
        CLType::String,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "claim",
        alloc::vec![
            Parameter::new("hashlock_hex", CLType::String),
            Parameter::new("preimage", CLType::List(alloc::boxed::Box::new(CLType::U8))),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "refund",
        alloc::vec![Parameter::new("hashlock_hex", CLType::String)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "get_status",
        alloc::vec![Parameter::new("hashlock_hex", CLType::String)],
        CLType::Tuple2([alloc::boxed::Box::new(CLType::U8), alloc::boxed::Box::new(CLType::U512)]),
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    let mut named_keys = NamedKeys::new();
    let caller = runtime::get_caller();
    let installer_uref = storage::new_uref(caller);
    named_keys.insert(INSTALLER_KEY.to_string(), installer_uref.into());
    let count_uref = storage::new_uref(0u64);
    named_keys.insert(SWAP_COUNT_KEY.to_string(), count_uref.into());

    let package_hash_name: String = runtime::get_named_arg("package_hash_name");
    let contract_hash_name: String = runtime::get_named_arg("contract_hash_name");
    let (contract_hash, _version) = storage::new_contract(
        entry_points,
        Some(named_keys),
        Some(package_hash_name.clone()),
        None,
        None,
    );
    runtime::put_key(&contract_hash_name, contract_hash.into());
}
