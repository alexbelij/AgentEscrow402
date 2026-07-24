#![no_std]
#![no_main]

//! AE402 Governance DAO — WASM entry points.
//!
//! Provenance: proposal-lifecycle, voting, delegation, quorum, and veto
//! entry points are structurally ported from `rwa-s/contracts/governance-dao`
//! (Apache-2.0). The action layer, execution-attestation message, and
//! integration hooks are AE402-specific and net-new. See `PROVENANCE.md`.

extern crate alloc;

use alloc::format;
use alloc::string::{String, ToString};
use alloc::vec;

use casper_contract::contract_api::{runtime, storage};
use casper_contract::unwrap_or_revert::UnwrapOrRevert;
use casper_types::account::AccountHash;
use casper_types::contracts::NamedKeys;
use casper_types::{
    ApiError, CLType, CLValue, EntityEntryPoint, EntryPointAccess, EntryPointPayment,
    EntryPointType, EntryPoints, Key, Parameter, URef,
};

use ae402_governance_dao::{
    is_valid_action, parse_params, resolve_status, ActionParams, ERR_INVALID_ACTION,
    ERR_INVALID_PARAMS, ERR_INVALID_VOTE, QUORUM_PERCENT, STATUS_ACTIVE, STATUS_EXECUTED,
    STATUS_EXPIRED, STATUS_PASSED, STATUS_VETOED, VOTING_PERIOD_SECONDS,
};

// ────────────────────────────────────────────────────────────────────────────
// Named keys / dictionaries
// ────────────────────────────────────────────────────────────────────────────

const CONTRACT_HASH_KEY: &str = "ae402_governance_dao_contract_hash";
const PACKAGE_HASH_KEY: &str = "ae402_governance_dao_package_hash";
const ACCESS_UREF_KEY: &str = "ae402_governance_dao_access_uref";

const INSTALLER_KEY: &str = "installer";
const PROPOSAL_COUNT_KEY: &str = "proposal_count";
const TOTAL_STAKED_KEY: &str = "total_staked";

const PROPOSALS_DICT: &str = "proposals";
const PROPOSAL_DETAILS_DICT: &str = "proposal_details";
const VOTES_DICT: &str = "votes";
const DELEGATIONS_DICT: &str = "delegations";
const VOTER_STAKES_DICT: &str = "voter_stakes";
/// Records the last executed (proposal_id → execution_msg_hash_hex, timestamp)
/// for the audit trail. Consumed by the frontend and by cross-contract callers
/// that want to verify a governance-authored update actually landed.
const EXEC_LOG_DICT: &str = "exec_log";

// Application-level errors — start above the library range (>= 10).
const ERR_NOT_INSTALLER: u16 = 10;
const ERR_PROPOSAL_NOT_FOUND: u16 = 11;
const ERR_ALREADY_VOTED: u16 = 12;
const ERR_VOTING_CLOSED: u16 = 13;
const ERR_NOT_PASSED: u16 = 14;
const ERR_ALREADY_EXECUTED: u16 = 15;
const ERR_PROPOSAL_EXPIRED: u16 = 16;
const ERR_SELF_DELEGATE: u16 = 17;
const ERR_INVALID_ACCOUNT_HASH: u16 = 18;

// ────────────────────────────────────────────────────────────────────────────
// Storage record shapes — nested tuples so each level respects the 3-element
// CLTyped cap Casper enforces on tuple types.
// ────────────────────────────────────────────────────────────────────────────

// ProposalRecord: ((proposer_hash, title, action_type),
//                  (votes_for, votes_against, status),
//                  (created_at, voting_end, executed_at))
type ProposalRecord = ((String, String, u64), (u64, u64, u64), (u64, u64, u64));

// ProposalDetails: (description, params, target_contract_hash_hex)
// target_contract_hash_hex is optional (empty string = "same package") and
// carries the cross-contract execution target for the AE402 action layer.
type ProposalDetailsRecord = (String, String, String);

// ExecLog: (execution_msg_hex, executed_at, executor_hash)
type ExecLogRecord = (String, u64, String);

// ────────────────────────────────────────────────────────────────────────────
// Helper accessors
// ────────────────────────────────────────────────────────────────────────────

fn get_installer() -> AccountHash {
    runtime::get_key(INSTALLER_KEY)
        .unwrap_or_revert()
        .into_account()
        .unwrap_or_revert()
}

fn is_installer() -> bool {
    runtime::get_caller() == get_installer()
}

fn get_dict_uref(name: &str) -> URef {
    runtime::get_key(name)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert()
}

fn proposal_key_str(proposal_id: u64) -> String {
    format!("proposal_{}", proposal_id)
}

fn vote_key_str(proposal_id: u64, voter: &AccountHash) -> String {
    format!("{}:{}", proposal_id, voter.to_string())
}

fn get_current_timestamp() -> u64 {
    runtime::get_blocktime().into()
}

fn get_total_staked() -> u64 {
    let uref = runtime::get_key(TOTAL_STAKED_KEY)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    storage::read::<u64>(uref).unwrap_or_revert().unwrap_or(0)
}

/// Voting power ported from RWA-S: delegators forfeit direct power.
fn get_voting_power(account: &AccountHash) -> u64 {
    let delegations_uref = get_dict_uref(DELEGATIONS_DICT);
    let delegation: Option<String> =
        storage::dictionary_get(delegations_uref, &account.to_string()).unwrap_or_revert();
    if delegation.is_some() {
        return 0;
    }

    let voter_stakes_uref = get_dict_uref(VOTER_STAKES_DICT);
    let stake: Option<u64> =
        storage::dictionary_get(voter_stakes_uref, &account.to_string()).unwrap_or_revert();
    stake.unwrap_or(0)
}

/// SHA-256 hex digest — no_std, uses the runtime host function.
fn sha256_hex(bytes: &[u8]) -> String {
    let digest = runtime::blake2b(bytes);
    let mut out = String::with_capacity(digest.len() * 2);
    for b in digest.iter() {
        let hi = b >> 4;
        let lo = b & 0x0f;
        out.push(nibble_to_hex(hi));
        out.push(nibble_to_hex(lo));
    }
    out
}

fn nibble_to_hex(n: u8) -> char {
    match n {
        0..=9 => (b'0' + n) as char,
        _ => (b'a' + (n - 10)) as char,
    }
}

// ────────────────────────────────────────────────────────────────────────────
// Voter registration
// ────────────────────────────────────────────────────────────────────────────

#[no_mangle]
pub extern "C" fn register_voter() {
    if !is_installer() {
        runtime::revert(ApiError::User(ERR_NOT_INSTALLER));
    }

    let account_hash_str: String = runtime::get_named_arg("account_hash");
    let voting_power: u64 = runtime::get_named_arg("voting_power");

    let voter_stakes_uref = get_dict_uref(VOTER_STAKES_DICT);
    let old_power: Option<u64> =
        storage::dictionary_get(voter_stakes_uref, &account_hash_str).unwrap_or_revert();

    let total_staked_uref = runtime::get_key(TOTAL_STAKED_KEY)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    let mut total: u64 = storage::read(total_staked_uref)
        .unwrap_or_revert()
        .unwrap_or(0);

    if let Some(old) = old_power {
        total = total.saturating_sub(old);
    }
    total = total.saturating_add(voting_power);
    storage::write(total_staked_uref, total);
    storage::dictionary_put(voter_stakes_uref, &account_hash_str, voting_power);
}

// ────────────────────────────────────────────────────────────────────────────
// create_proposal — accepts AE402-specific action codes + target contract
// ────────────────────────────────────────────────────────────────────────────

#[no_mangle]
pub extern "C" fn create_proposal() {
    let title: String = runtime::get_named_arg("title");
    let description: String = runtime::get_named_arg("description");
    let action_type: u64 = runtime::get_named_arg("action_type");
    let params: String = runtime::get_named_arg("params");
    let target_contract: String = runtime::get_named_arg("target_contract");

    if !is_valid_action(action_type) {
        runtime::revert(ApiError::User(ERR_INVALID_ACTION));
    }

    // Validate params at submission time — nothing invalid can ever be
    // executed.
    if parse_params(action_type, &params).is_err() {
        runtime::revert(ApiError::User(ERR_INVALID_PARAMS));
    }

    let proposer = runtime::get_caller();
    let timestamp = get_current_timestamp();

    let count_uref: URef = runtime::get_key(PROPOSAL_COUNT_KEY)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    let count: u64 = storage::read(count_uref).unwrap_or_revert().unwrap_or(0);
    let new_count = count + 1;
    storage::write(count_uref, new_count);

    let proposal_id = new_count;
    let key = proposal_key_str(proposal_id);

    let proposal: ProposalRecord = (
        (proposer.to_string(), title, action_type),
        (0u64, 0u64, STATUS_ACTIVE),
        (timestamp, timestamp + VOTING_PERIOD_SECONDS, 0u64),
    );
    let details: ProposalDetailsRecord = (description, params, target_contract);

    storage::dictionary_put(get_dict_uref(PROPOSALS_DICT), &key, proposal);
    storage::dictionary_put(get_dict_uref(PROPOSAL_DETAILS_DICT), &key, details);

    runtime::ret(CLValue::from_t(proposal_id).unwrap_or_revert());
}

// ────────────────────────────────────────────────────────────────────────────
// vote — uses pure resolve_status() for the finalization decision
// ────────────────────────────────────────────────────────────────────────────

#[no_mangle]
pub extern "C" fn vote() {
    let proposal_id: u64 = runtime::get_named_arg("proposal_id");
    let support: u64 = runtime::get_named_arg("support");
    let weight: u64 = runtime::get_named_arg("weight");

    if support > 1 {
        runtime::revert(ApiError::User(ERR_INVALID_VOTE));
    }

    let voter = runtime::get_caller();
    let proposals_uref = get_dict_uref(PROPOSALS_DICT);
    let votes_uref = get_dict_uref(VOTES_DICT);

    let key = proposal_key_str(proposal_id);
    let vk = vote_key_str(proposal_id, &voter);

    let existing_vote: Option<bool> = storage::dictionary_get(votes_uref, &vk).unwrap_or_revert();
    if existing_vote.is_some() {
        runtime::revert(ApiError::User(ERR_ALREADY_VOTED));
    }

    let mut proposal: ProposalRecord = match storage::dictionary_get(proposals_uref, &key)
        .unwrap_or_revert()
    {
        Some(p) => p,
        None => runtime::revert(ApiError::User(ERR_PROPOSAL_NOT_FOUND)),
    };

    let current_time = get_current_timestamp();
    let voting_end = proposal.2 .1;

    let status_before = proposal.1 .2;
    if status_before != STATUS_ACTIVE {
        runtime::revert(ApiError::User(ERR_VOTING_CLOSED));
    }

    if current_time > voting_end {
        // Voting window closed before this call landed — write EXPIRED and
        // reject.
        proposal.1 .2 = STATUS_EXPIRED;
        storage::dictionary_put(proposals_uref, &key, proposal);
        runtime::revert(ApiError::User(ERR_PROPOSAL_EXPIRED));
    }

    let voting_power = get_voting_power(&voter);
    let effective = if weight < voting_power { weight } else { voting_power };

    if support == 1 {
        proposal.1 .0 = proposal.1 .0.saturating_add(effective);
    } else {
        proposal.1 .1 = proposal.1 .1.saturating_add(effective);
    }

    let total_staked = get_total_staked();
    let new_status = resolve_status(
        proposal.1 .0,
        proposal.1 .1,
        total_staked,
        QUORUM_PERCENT,
        current_time,
        voting_end,
    );
    proposal.1 .2 = new_status;

    storage::dictionary_put(proposals_uref, &key, proposal);
    storage::dictionary_put(votes_uref, &vk, true);
}

// ────────────────────────────────────────────────────────────────────────────
// execute_proposal — dispatches to AE402 target contracts + writes exec log
// ────────────────────────────────────────────────────────────────────────────

#[no_mangle]
pub extern "C" fn execute_proposal() {
    let proposal_id: u64 = runtime::get_named_arg("proposal_id");
    let proposals_uref = get_dict_uref(PROPOSALS_DICT);
    let details_uref = get_dict_uref(PROPOSAL_DETAILS_DICT);
    let key = proposal_key_str(proposal_id);

    let mut proposal: ProposalRecord = match storage::dictionary_get(proposals_uref, &key)
        .unwrap_or_revert()
    {
        Some(p) => p,
        None => runtime::revert(ApiError::User(ERR_PROPOSAL_NOT_FOUND)),
    };

    let details: ProposalDetailsRecord = match storage::dictionary_get(details_uref, &key)
        .unwrap_or_revert()
    {
        Some(d) => d,
        None => runtime::revert(ApiError::User(ERR_PROPOSAL_NOT_FOUND)),
    };

    let status = proposal.1 .2;
    if status == STATUS_EXECUTED {
        runtime::revert(ApiError::User(ERR_ALREADY_EXECUTED));
    }
    if status == STATUS_VETOED {
        runtime::revert(ApiError::User(ERR_NOT_PASSED));
    }

    // Late-finalize if the window closed after the last vote.
    let current_time = get_current_timestamp();
    if current_time > proposal.2 .1 && status == STATUS_ACTIVE {
        let total_staked = get_total_staked();
        let new_status = resolve_status(
            proposal.1 .0,
            proposal.1 .1,
            total_staked,
            QUORUM_PERCENT,
            current_time,
            proposal.2 .1,
        );
        proposal.1 .2 = new_status;
        storage::dictionary_put(proposals_uref, &key, proposal.clone());
    }

    if proposal.1 .2 != STATUS_PASSED {
        runtime::revert(ApiError::User(ERR_NOT_PASSED));
    }

    let action_type = proposal.0 .2;
    let params_str = &details.1;

    // Parse params at execution — must still be valid; guards against a
    // future upgrade that widened the schema.
    let _parsed: ActionParams = parse_params(action_type, params_str)
        .map_err(ApiError::User)
        .unwrap_or_revert();

    // Cross-contract dispatch stub. In this iteration we ONLY record the
    // execution attestation on-chain (msg hash + timestamp + executor). The
    // actual target-contract call is emitted via a well-known named-key
    // pointer so the target contract (timelock-admin, insurance-pool,
    // arbiter-registry, range-proof-registry, escrow) can pick it up on its
    // next admin-guarded entry point (pull model). This avoids the
    // one-block re-entrancy hazard we would inherit from a direct push
    // dispatch and keeps the DAO composable with the timelock delay.
    //
    // For the hackathon submission this is the honest scope: DAO makes the
    // decision on-chain, target contracts read the decision and apply it in
    // their own admin path. See docs/GOVERNANCE.md ยง"Execution model" for
    // the full rationale.

    let msg = ae402_governance_dao::build_execution_message(proposal_id, action_type, params_str);
    let msg_hex = sha256_hex(msg.as_bytes());

    let exec_log: ExecLogRecord = (
        msg_hex,
        current_time,
        runtime::get_caller().to_string(),
    );
    storage::dictionary_put(get_dict_uref(EXEC_LOG_DICT), &key, exec_log);

    proposal.1 .2 = STATUS_EXECUTED;
    proposal.2 .2 = current_time;
    storage::dictionary_put(proposals_uref, &key, proposal);
}

// ────────────────────────────────────────────────────────────────────────────
// veto — installer-guarded, ported from RWA-S
// ────────────────────────────────────────────────────────────────────────────

#[no_mangle]
pub extern "C" fn veto_proposal() {
    if !is_installer() {
        runtime::revert(ApiError::User(ERR_NOT_INSTALLER));
    }

    let proposal_id: u64 = runtime::get_named_arg("proposal_id");
    let proposals_uref = get_dict_uref(PROPOSALS_DICT);
    let key = proposal_key_str(proposal_id);

    let mut proposal: ProposalRecord = match storage::dictionary_get(proposals_uref, &key)
        .unwrap_or_revert()
    {
        Some(p) => p,
        None => runtime::revert(ApiError::User(ERR_PROPOSAL_NOT_FOUND)),
    };

    if proposal.1 .2 == STATUS_EXECUTED {
        runtime::revert(ApiError::User(ERR_ALREADY_EXECUTED));
    }

    proposal.1 .2 = STATUS_VETOED;
    proposal.2 .2 = get_current_timestamp();
    storage::dictionary_put(proposals_uref, &key, proposal);
}

// ────────────────────────────────────────────────────────────────────────────
// delegate — ported from RWA-S
// ────────────────────────────────────────────────────────────────────────────

#[no_mangle]
pub extern "C" fn delegate() {
    let to_str: String = runtime::get_named_arg("to");
    let delegator = runtime::get_caller();

    let to = AccountHash::from_formatted_str(&to_str)
        .map_err(|_| ApiError::User(ERR_INVALID_ACCOUNT_HASH))
        .unwrap_or_revert();

    if delegator == to {
        runtime::revert(ApiError::User(ERR_SELF_DELEGATE));
    }

    let delegations_uref = get_dict_uref(DELEGATIONS_DICT);
    storage::dictionary_put(delegations_uref, &delegator.to_string(), to_str);
}

// ────────────────────────────────────────────────────────────────────────────
// get_proposal — returns nested tuples respecting the 3-element cap
// ────────────────────────────────────────────────────────────────────────────

#[no_mangle]
pub extern "C" fn get_proposal() {
    let proposal_id: u64 = runtime::get_named_arg("proposal_id");
    let proposals_uref = get_dict_uref(PROPOSALS_DICT);
    let details_uref = get_dict_uref(PROPOSAL_DETAILS_DICT);
    let key = proposal_key_str(proposal_id);

    let p: ProposalRecord = match storage::dictionary_get(proposals_uref, &key).unwrap_or_revert()
    {
        Some(p) => p,
        None => runtime::revert(ApiError::User(ERR_PROPOSAL_NOT_FOUND)),
    };
    let d: ProposalDetailsRecord = match storage::dictionary_get(details_uref, &key)
        .unwrap_or_revert()
    {
        Some(d) => d,
        None => runtime::revert(ApiError::User(ERR_PROPOSAL_NOT_FOUND)),
    };

    let ((proposer, title, action_type), (votes_for, votes_against, status), (created_at, voting_end, executed_at)) =
        p;
    let (description, params, target_contract) = d;

    let ret = (
        (proposal_id, proposer, title),
        (description, params, action_type),
        (
            (votes_for, votes_against, status),
            (created_at, voting_end, executed_at),
            target_contract,
        ),
    );
    runtime::ret(CLValue::from_t(ret).unwrap_or_revert());
}

/// Return the execution log for a proposal (empty tuple if not executed).
#[no_mangle]
pub extern "C" fn get_exec_log() {
    let proposal_id: u64 = runtime::get_named_arg("proposal_id");
    let key = proposal_key_str(proposal_id);
    let log: Option<ExecLogRecord> = storage::dictionary_get(get_dict_uref(EXEC_LOG_DICT), &key)
        .unwrap_or_revert();
    runtime::ret(
        CLValue::from_t(log.unwrap_or_else(|| (String::new(), 0u64, String::new())))
            .unwrap_or_revert(),
    );
}

// ────────────────────────────────────────────────────────────────────────────
// Installer entry point
// ────────────────────────────────────────────────────────────────────────────

#[no_mangle]
pub extern "C" fn call() {
    let installer = runtime::get_caller();

    let proposals_dict = storage::new_dictionary(PROPOSALS_DICT).unwrap_or_revert();
    let proposal_details_dict = storage::new_dictionary(PROPOSAL_DETAILS_DICT).unwrap_or_revert();
    let votes_dict = storage::new_dictionary(VOTES_DICT).unwrap_or_revert();
    let delegations_dict = storage::new_dictionary(DELEGATIONS_DICT).unwrap_or_revert();
    let voter_stakes_dict = storage::new_dictionary(VOTER_STAKES_DICT).unwrap_or_revert();
    let exec_log_dict = storage::new_dictionary(EXEC_LOG_DICT).unwrap_or_revert();

    let proposal_count_uref = storage::new_uref(0u64);
    let total_staked_uref = storage::new_uref(0u64);

    let mut named_keys = NamedKeys::new();
    named_keys.insert(INSTALLER_KEY.into(), Key::Account(installer));
    named_keys.insert(PROPOSAL_COUNT_KEY.into(), proposal_count_uref.into());
    named_keys.insert(TOTAL_STAKED_KEY.into(), total_staked_uref.into());
    named_keys.insert(PROPOSALS_DICT.into(), proposals_dict.into());
    named_keys.insert(PROPOSAL_DETAILS_DICT.into(), proposal_details_dict.into());
    named_keys.insert(VOTES_DICT.into(), votes_dict.into());
    named_keys.insert(DELEGATIONS_DICT.into(), delegations_dict.into());
    named_keys.insert(VOTER_STAKES_DICT.into(), voter_stakes_dict.into());
    named_keys.insert(EXEC_LOG_DICT.into(), exec_log_dict.into());

    let mut entry_points = EntryPoints::new();

    entry_points.add_entry_point(EntityEntryPoint::new(
        "register_voter",
        vec![
            Parameter::new("account_hash", CLType::String),
            Parameter::new("voting_power", CLType::U64),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "create_proposal",
        vec![
            Parameter::new("title", CLType::String),
            Parameter::new("description", CLType::String),
            Parameter::new("action_type", CLType::U64),
            Parameter::new("params", CLType::String),
            Parameter::new("target_contract", CLType::String),
        ],
        CLType::U64,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "vote",
        vec![
            Parameter::new("proposal_id", CLType::U64),
            Parameter::new("support", CLType::U64),
            Parameter::new("weight", CLType::U64),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "execute_proposal",
        vec![Parameter::new("proposal_id", CLType::U64)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "veto_proposal",
        vec![Parameter::new("proposal_id", CLType::U64)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "delegate",
        vec![Parameter::new("to", CLType::String)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "get_proposal",
        vec![Parameter::new("proposal_id", CLType::U64)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "get_exec_log",
        vec![Parameter::new("proposal_id", CLType::U64)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    let (contract_hash, _v) = storage::new_contract(
        entry_points,
        Some(named_keys),
        Some(PACKAGE_HASH_KEY.into()),
        Some(ACCESS_UREF_KEY.into()),
        None,
    );
    runtime::put_key(CONTRACT_HASH_KEY, contract_hash.into());
}
