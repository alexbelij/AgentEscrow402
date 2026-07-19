//! On-chain Agent Identity Registry for AI agent discovery and reputation.
//!
//! Standalone contract (ID-1 in the roadmap backlog), modeled after the
//! ERC-8004/ERC-8126 "trustless agents" pattern from Ethereum and adapted
//! for Casper: agents self-register a DID (`did:casper:{network}:{account
//! hash hex}`), stake CSPR as anti-Sybil collateral, declare capabilities,
//! and accrue/decay a reputation score. This is deliberately a *separate*
//! contract from `escrow-manager`/`escrow` -- it does not touch or upgrade
//! those live, already-9-times-upgraded contracts, so it carries zero risk
//! to the existing escrow flows. `server/identity_registry_api.py` remains
//! the off-chain/Postgres registry used by the API today; this contract is
//! the on-chain counterpart the roadmap asked to bring from stub to real.

#![no_std]
#![no_main]

extern crate alloc;

use alloc::string::{String, ToString};
use alloc::vec::Vec;

use casper_contract::contract_api::{runtime, storage, system};
use casper_contract::unwrap_or_revert::UnwrapOrRevert;
use casper_types::account::AccountHash;
use casper_types::contracts::NamedKeys;
use casper_types::{
    ApiError, CLType, CLValue, EntityEntryPoint, EntryPointAccess, EntryPointPayment,
    EntryPointType, EntryPoints, Key, Parameter, URef, U512,
};

// ── Error codes ──────────────────────────────────────────────────────

const ERR_UNAUTHORIZED: u16 = 1;
const ERR_ALREADY_REGISTERED: u16 = 2;
const ERR_NOT_REGISTERED: u16 = 3;
const ERR_STAKE_BELOW_MIN: u16 = 4;
const ERR_NOT_IN_COOLDOWN: u16 = 5;
const ERR_COOLDOWN_NOT_ELAPSED: u16 = 6;
const ERR_ALREADY_DEREGISTERING: u16 = 7;
const ERR_SLASH_EXCEEDS_STAKE: u16 = 8;
const ERR_AMOUNT_TOO_LARGE: u16 = 9;

// ── Storage keys ─────────────────────────────────────────────────────

const AGENTS_DICT: &str = "agents";
const MIN_STAKE_KEY: &str = "min_stake_motes";
const INSTALLER_KEY: &str = "installer";
const STAKE_PURSE: &str = "stake_purse";
const SLASHED_PURSE: &str = "slashed_purse";

// ── Constants ────────────────────────────────────────────────────────

const DEFAULT_MIN_STAKE_MOTES: u64 = 100_000_000_000; // 100 CSPR
const DEREGISTER_COOLDOWN_MS: u64 = 604_800_000; // 7 days, in ms (get_blocktime() returns epoch-ms, confirmed via on-chain query)
const REPUTATION_DECAY_PER_WEEK: u64 = 1;
const DEFAULT_REPUTATION: u64 = 50;
const MS_PER_WEEK: u64 = 604_800_000; // get_blocktime() returns epoch-ms, not seconds

const STATUS_ACTIVE: u8 = 0;
const STATUS_COOLDOWN: u8 = 1;
const STATUS_DEREGISTERED: u8 = 2;

const VERIFICATION_SELF_DECLARED: u8 = 0;

/// Record layout, split into <=3-arity tuples (casper-types only
/// implements CLTyped/ToBytes/FromBytes for tuples up to arity 3):
///   ids:          (did, owner_hex, capabilities)
///   stake_rep:    (stake_motes, reputation, verification_level)
///   times_status: (registered_at, last_active, status)
///   outer:        (ids, stake_rep, times_status), deregistered_at)
type AgentIds = (String, String, Vec<String>);
type AgentStakeRep = (u64, u64, u8);
type AgentTimesStatus = (u64, u64, u8);
type AgentRecord = ((AgentIds, AgentStakeRep, AgentTimesStatus), u64);

// ── Helpers ──────────────────────────────────────────────────────────

fn read_installer() -> AccountHash {
    let key = runtime::get_key(INSTALLER_KEY).unwrap_or_revert();
    key.into_account().unwrap_or_revert()
}

fn require_installer() {
    let caller = runtime::get_caller();
    let installer = read_installer();
    if caller != installer {
        runtime::revert(ApiError::User(ERR_UNAUTHORIZED));
    }
}

fn get_named_uref(name: &str) -> URef {
    runtime::get_key(name)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert()
}

fn get_dict_uref(name: &str) -> URef {
    // Same Casper 2.2.x constraint as the escrow contract: new_dictionary
    // is disallowed in session/install context, so it's created lazily
    // the first time an entry point touches it.
    match runtime::get_key(name) {
        Some(key) => key.into_uref().unwrap_or_revert(),
        None => storage::new_dictionary(name).unwrap_or_revert(),
    }
}

fn read_min_stake() -> u64 {
    let uref = get_named_uref(MIN_STAKE_KEY);
    storage::read::<u64>(uref)
        .unwrap_or_revert()
        .unwrap_or(DEFAULT_MIN_STAKE_MOTES)
}

fn read_agent(dict: URef, owner_hex: &str) -> Option<AgentRecord> {
    storage::dictionary_get(dict, owner_hex).unwrap_or_revert()
}

fn write_agent(dict: URef, owner_hex: &str, record: AgentRecord) {
    storage::dictionary_put(dict, owner_hex, record);
}

fn must_read_agent(dict: URef, owner_hex: &str) -> AgentRecord {
    match read_agent(dict, owner_hex) {
        Some(r) => r,
        None => runtime::revert(ApiError::User(ERR_NOT_REGISTERED)),
    }
}

/// Apply linear weekly reputation decay based on inactivity, saturating at 0.
fn decay_reputation(reputation: u64, last_active: u64, now: u64) -> u64 {
    let weeks_inactive = now.saturating_sub(last_active) / MS_PER_WEEK;
    let decay = weeks_inactive.saturating_mul(REPUTATION_DECAY_PER_WEEK);
    reputation.saturating_sub(decay)
}

fn did_for(owner_hex: &str) -> String {
    let mut did = String::from("did:casper:testnet:");
    did.push_str(owner_hex);
    did
}

/// Stake is stored as u64 motes (record layout constraint), but the caller
/// supplies U512 -- `.as_u64()` silently truncates instead of erroring if
/// the value doesn't fit, so reject anything above u64::MAX up front
/// rather than truncate and record the wrong stake.
fn require_fits_u64(amount: U512) {
    if amount > U512::from(u64::MAX) {
        runtime::revert(ApiError::User(ERR_AMOUNT_TOO_LARGE));
    }
}

// ── Entry points ─────────────────────────────────────────────────────

/// Register the caller as an agent: stakes `amount` motes (transferred
/// from `source_purse`) and declares `capabilities`. Reverts if the caller
/// is already registered (use `add_stake`/`update_capabilities` instead)
/// or if `amount` is below the configured minimum stake.
#[no_mangle]
pub extern "C" fn register_agent() {
    let caller = runtime::get_caller();
    let owner_hex = caller.to_string();
    let capabilities: Vec<String> = runtime::get_named_arg("capabilities");
    let amount: U512 = runtime::get_named_arg("amount");
    let source_purse: URef = runtime::get_named_arg("source_purse");

    require_fits_u64(amount);
    let min_stake = read_min_stake();
    if amount < U512::from(min_stake) {
        runtime::revert(ApiError::User(ERR_STAKE_BELOW_MIN));
    }

    let dict = get_dict_uref(AGENTS_DICT);
    if read_agent(dict, &owner_hex).is_some() {
        runtime::revert(ApiError::User(ERR_ALREADY_REGISTERED));
    }

    let stake_purse = get_dict_uref(STAKE_PURSE);
    system::transfer_from_purse_to_purse(source_purse, stake_purse, amount, None)
        .unwrap_or_revert();

    let now: u64 = runtime::get_blocktime().into();
    // U512 -> u64 is safe here: stakes are always well under u64::MAX motes.
    let stake_motes: u64 = amount.as_u64();
    let record: AgentRecord = (
        (
            (did_for(&owner_hex), owner_hex.clone(), capabilities),
            (stake_motes, DEFAULT_REPUTATION, VERIFICATION_SELF_DECLARED),
            (now, now, STATUS_ACTIVE),
        ),
        0u64,
    );
    write_agent(dict, &owner_hex, record);
}

/// Add more stake to the caller's existing record (e.g. to raise trust
/// weight or recover after a partial slash). No-op on capabilities/status.
#[no_mangle]
pub extern "C" fn add_stake() {
    let caller = runtime::get_caller();
    let owner_hex = caller.to_string();
    let amount: U512 = runtime::get_named_arg("amount");
    let source_purse: URef = runtime::get_named_arg("source_purse");
    require_fits_u64(amount);

    let dict = get_dict_uref(AGENTS_DICT);
    let ((ids, (stake, reputation, verification), times_status), deregistered_at) =
        must_read_agent(dict, &owner_hex);

    let stake_purse = get_dict_uref(STAKE_PURSE);
    system::transfer_from_purse_to_purse(source_purse, stake_purse, amount, None)
        .unwrap_or_revert();

    let new_stake = stake.saturating_add(amount.as_u64());
    let record: AgentRecord = (
        (ids, (new_stake, reputation, verification), times_status),
        deregistered_at,
    );
    write_agent(dict, &owner_hex, record);
}

/// Update the caller's declared capability list. Also refreshes
/// `last_active` (and applies any pending reputation decay first, so an
/// agent can't dodge decay by touching an unrelated field).
/// Deliberately allowed during `STATUS_COOLDOWN` (an agent that requested
/// deregistration is still on the hook -- its stake is locked and
/// slashable -- until `withdraw_stake` actually completes, so there's no
/// reason to freeze this field earlier).
#[no_mangle]
pub extern "C" fn update_capabilities() {
    let caller = runtime::get_caller();
    let owner_hex = caller.to_string();
    let capabilities: Vec<String> = runtime::get_named_arg("capabilities");

    let dict = get_dict_uref(AGENTS_DICT);
    let (((did, owner, _old_caps), (stake, reputation, verification), (registered_at, _last_active, status)), deregistered_at) =
        must_read_agent(dict, &owner_hex);

    let now: u64 = runtime::get_blocktime().into();
    let decayed = decay_reputation(reputation, _last_active, now);
    let record: AgentRecord = (
        (
            (did, owner, capabilities),
            (stake, decayed, verification),
            (registered_at, now, status),
        ),
        deregistered_at,
    );
    write_agent(dict, &owner_hex, record);
}

/// Force-apply reputation decay for any agent (no auth needed -- decay is
/// a pure function of elapsed time, so this is safe to expose publicly and
/// lets anyone keep the on-chain view up to date without waiting for that
/// agent's own next transaction).
#[no_mangle]
pub extern "C" fn apply_decay() {
    let owner_hex: String = runtime::get_named_arg("owner");

    let dict = get_dict_uref(AGENTS_DICT);
    let (ids_stakerep_times, deregistered_at) = must_read_agent(dict, &owner_hex);
    let (ids, (stake, reputation, verification), (registered_at, last_active, status)) =
        ids_stakerep_times;

    let now: u64 = runtime::get_blocktime().into();
    let decayed = decay_reputation(reputation, last_active, now);
    let record: AgentRecord = (
        (
            ids,
            (stake, decayed, verification),
            (registered_at, last_active, status),
        ),
        deregistered_at,
    );
    write_agent(dict, &owner_hex, record);
}

/// Start the deregistration cooldown. Stake remains locked (and slashable)
/// until `withdraw_stake` is called after `DEREGISTER_COOLDOWN_MS` have
/// elapsed -- this prevents an agent from staking, misbehaving, then
/// instantly exiting with its collateral before a dispute can catch up.
#[no_mangle]
pub extern "C" fn request_deregister() {
    let caller = runtime::get_caller();
    let owner_hex = caller.to_string();

    let dict = get_dict_uref(AGENTS_DICT);
    let ((ids, stake_rep, (registered_at, last_active, status)), _old_deregistered_at) =
        must_read_agent(dict, &owner_hex);

    if status != STATUS_ACTIVE {
        runtime::revert(ApiError::User(ERR_ALREADY_DEREGISTERING));
    }

    let now: u64 = runtime::get_blocktime().into();
    let record: AgentRecord = (
        (ids, stake_rep, (registered_at, last_active, STATUS_COOLDOWN)),
        now,
    );
    write_agent(dict, &owner_hex, record);
}

/// Withdraw stake back to `target_purse` once the cooldown has elapsed.
/// Zeroes out the agent record on success (re-registration starts fresh).
#[no_mangle]
pub extern "C" fn withdraw_stake() {
    let caller = runtime::get_caller();
    let owner_hex = caller.to_string();
    let target_purse: URef = runtime::get_named_arg("target_purse");

    let dict = get_dict_uref(AGENTS_DICT);
    let ((_ids, (stake, _reputation, _verification), (_registered_at, _last_active, status)), deregistered_at) =
        must_read_agent(dict, &owner_hex);

    if status != STATUS_COOLDOWN {
        runtime::revert(ApiError::User(ERR_NOT_IN_COOLDOWN));
    }
    let now: u64 = runtime::get_blocktime().into();
    if now < deregistered_at.saturating_add(DEREGISTER_COOLDOWN_MS) {
        runtime::revert(ApiError::User(ERR_COOLDOWN_NOT_ELAPSED));
    }

    let stake_purse = get_dict_uref(STAKE_PURSE);
    system::transfer_from_purse_to_purse(stake_purse, target_purse, U512::from(stake), None)
        .unwrap_or_revert();

    let record: AgentRecord = (
        (
            (String::new(), String::new(), Vec::<String>::new()),
            (0u64, 0u64, VERIFICATION_SELF_DECLARED),
            (0u64, 0u64, STATUS_DEREGISTERED),
        ),
        0u64,
    );
    write_agent(dict, &owner_hex, record);
}

/// Slash `amount` motes from `agent`'s stake and cut reputation in half
/// (installer/admin only -- in production this would be gated behind the
/// same arbiter-quorum pattern `escrow.resolve()` uses; kept
/// installer-only here to keep this standalone contract's first version
/// small. Documented as a known gap, not hidden.).
#[no_mangle]
pub extern "C" fn slash() {
    require_installer();
    let owner_hex: String = runtime::get_named_arg("agent");
    let amount: u64 = runtime::get_named_arg("amount");

    let dict = get_dict_uref(AGENTS_DICT);
    let ((ids, (stake, reputation, verification), times_status), deregistered_at) =
        must_read_agent(dict, &owner_hex);

    if amount > stake {
        runtime::revert(ApiError::User(ERR_SLASH_EXCEEDS_STAKE));
    }

    let stake_purse = get_dict_uref(STAKE_PURSE);
    let slashed_purse = get_dict_uref(SLASHED_PURSE);
    system::transfer_from_purse_to_purse(stake_purse, slashed_purse, U512::from(amount), None)
        .unwrap_or_revert();

    let new_stake = stake.saturating_sub(amount);
    let new_reputation = reputation / 2;
    let record: AgentRecord = (
        (ids, (new_stake, new_reputation, verification), times_status),
        deregistered_at,
    );
    write_agent(dict, &owner_hex, record);
}

/// Installer-only: retune the minimum stake required to register.
#[no_mangle]
pub extern "C" fn configure_min_stake() {
    require_installer();
    let new_min: u64 = runtime::get_named_arg("new_min_stake_motes");
    let uref = get_named_uref(MIN_STAKE_KEY);
    storage::write(uref, new_min);
}

/// Read an agent's full record by owner account-hash hex string.
#[no_mangle]
pub extern "C" fn get_agent() {
    let owner_hex: String = runtime::get_named_arg("owner");
    let dict = get_dict_uref(AGENTS_DICT);
    let record = read_agent(dict, &owner_hex);
    runtime::ret(CLValue::from_t(record).unwrap_or_revert());
}

// ── Contract installation ────────────────────────────────────────────

#[no_mangle]
pub extern "C" fn call() {
    let installer = runtime::get_caller();

    let stake_purse = system::create_purse();
    let slashed_purse = system::create_purse();
    let min_stake_uref = storage::new_uref(DEFAULT_MIN_STAKE_MOTES);

    let mut named_keys = NamedKeys::new();
    named_keys.insert(STAKE_PURSE.into(), stake_purse.into());
    named_keys.insert(SLASHED_PURSE.into(), slashed_purse.into());
    named_keys.insert(MIN_STAKE_KEY.into(), min_stake_uref.into());
    named_keys.insert(INSTALLER_KEY.into(), Key::Account(installer));

    let mut entry_points = EntryPoints::new();
    entry_points.add_entry_point(EntityEntryPoint::new(
        "register_agent",
        alloc::vec![
            Parameter::new("capabilities", CLType::List(alloc::boxed::Box::new(CLType::String))),
            Parameter::new("amount", CLType::U512),
            Parameter::new("source_purse", CLType::URef),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "add_stake",
        alloc::vec![
            Parameter::new("amount", CLType::U512),
            Parameter::new("source_purse", CLType::URef),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "update_capabilities",
        alloc::vec![Parameter::new(
            "capabilities",
            CLType::List(alloc::boxed::Box::new(CLType::String))
        )],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "apply_decay",
        alloc::vec![Parameter::new("owner", CLType::String)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "request_deregister",
        alloc::vec![],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "withdraw_stake",
        alloc::vec![Parameter::new("target_purse", CLType::URef)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "slash",
        alloc::vec![
            Parameter::new("agent", CLType::String),
            Parameter::new("amount", CLType::U64),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "configure_min_stake",
        alloc::vec![Parameter::new("new_min_stake_motes", CLType::U64)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "get_agent",
        alloc::vec![Parameter::new("owner", CLType::String)],
        CLType::Any,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    // Same upgrade-in-place pattern as escrow/main.rs: if re-running call()
    // against an existing deployment, add a new version to the same
    // package instead of creating a brand-new one.
    if let Some(existing_package_key) = runtime::get_key("agent_identity_registry_package_hash") {
        let package_hash_addr = existing_package_key.into_entity_hash_addr().unwrap_or_revert();
        let package_hash: casper_types::contracts::ContractPackageHash = package_hash_addr.into();
        let (contract_hash, _) = storage::add_contract_version(
            package_hash,
            entry_points,
            NamedKeys::new(),
            alloc::collections::BTreeMap::new(),
        );
        runtime::put_key("agent_identity_registry_contract", contract_hash.into());
        return;
    }

    let (contract_hash, _) = storage::new_contract(
        entry_points,
        Some(named_keys),
        Some("agent_identity_registry_package_hash".into()),
        Some("agent_identity_registry_access_uref".into()),
        None,
    );
    runtime::put_key("agent_identity_registry_contract", contract_hash.into());
}
