#![no_std]
#![no_main]

extern crate alloc;

use alloc::boxed::Box;
use alloc::format;
use alloc::string::{String, ToString};
use alloc::vec;
use alloc::vec::Vec;

use casper_contract::contract_api::{runtime, storage, system};
use casper_contract::unwrap_or_revert::UnwrapOrRevert;
use casper_types::account::AccountHash;
use casper_types::contracts::NamedKeys;
use casper_types::{
    ApiError, CLType, CLValue, EntityEntryPoint, EntryPointAccess, EntryPointPayment, EntryPointType,
    EntryPoints, Key, Parameter, URef, U512,
};

// Constants for dictionary names and keys
const ARBITERS_DICT: &str = "arbiters_dict";
const ELECTIONS_DICT: &str = "elections_dict";
const VOTES_DICT: &str = "votes_dict";
const NONCE_KEY: &str = "nonce";
const INSTALLER_KEY: &str = "installer";
const ACTIVE_ARBITERS_LIST: &str = "active_arbiters_list"; // URef<Vec<String>>
const CONTRACT_PURSE: &str = "contract_purse";
const STAKE_PURSE: &str = "stake_purse";
const PRICE_BPS_KEY: &str = "price_bps"; // Basis points for revenue model

// Default values
const DEFAULT_PRICE_BPS: u64 = 0; // 0% fee by default
const DEFAULT_REPUTATION_SCORE: u64 = 50;
const DECAY_PERCENT_PER_WEEK: u64 = 5;

// Error codes
const ERR_NOT_INSTALLER: u16 = 1;
const ERR_ARBITER_EXISTS: u16 = 2;
const ERR_ARBITER_NOT_FOUND: u16 = 3;
const ERR_INVALID_STAKE: u16 = 4;
const ERR_ELECTION_EXISTS: u16 = 5;
const ERR_ELECTION_NOT_FOUND: u16 = 6;
const ERR_INSUFFICIENT_STAKE: u16 = 7;
const ERR_INSUFFICIENT_ARBITERS: u16 = 8;
const ERR_NOT_SELECTED_ARBITER: u16 = 9;
const ERR_ALREADY_VOTED: u16 = 10;
const ERR_ELECTION_RESOLVED: u16 = 11;

// ArbiterRecord: ((account_hash_str, stake, registered_block_time), (completed, disputed, last_active), (is_active, reputation, total_slashed))
type ArbiterRecord = ((String, U512, u64), (u64, u64, u64), (bool, u64, U512));

// ElectionRecord: ((dispute_id, seed, selection_count), (selected_arbiters_csv, status, resolved_block_time))
// status: 0=Pending, 1=Resolved, 2=Disputed
type ElectionRecord = ((String, String, u64), (String, u64, u64));

// VoteRecord: ((dispute_id, arbiter_account_hash_str, vote), (evidence, vote_block_time))
type VoteRecord = ((String, String, u64), (String, u64));

// Helper functions for storage access and contract logic

fn get_installer() -> AccountHash {
    let key: Key = runtime::get_key(INSTALLER_KEY).unwrap_or_revert();
    key.into_account().unwrap_or_revert()
}

fn assert_installer() {
    if runtime::get_caller() != get_installer() {
        runtime::revert(ApiError::User(ERR_NOT_INSTALLER));
    }
}

fn get_dict_uref(name: &str) -> URef {
    runtime::get_key(name)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert()
}

fn read_nonce() -> u64 {
    let uref = runtime::get_key(NONCE_KEY)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    storage::read::<u64>(uref)
        .unwrap_or_revert()
        .unwrap_or(0u64)
}

fn increment_nonce() {
    let uref = runtime::get_key(NONCE_KEY)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    let nonce = read_nonce();
    storage::write(uref, nonce + 1);
}

fn read_price_bps() -> u64 {
    let uref = runtime::get_key(PRICE_BPS_KEY)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    storage::read::<u64>(uref)
        .unwrap_or_revert()
        .unwrap_or(DEFAULT_PRICE_BPS)
}

fn reputation_score(completed: u64, disputed: u64, weeks_inactive: u64) -> u64 {
    if completed == 0 {
        return DEFAULT_REPUTATION_SCORE;
    }
    let base = 100u64.saturating_sub(disputed.saturating_mul(10).min(50));
    let decay = DECAY_PERCENT_PER_WEEK
        .saturating_mul(weeks_inactive)
        .min(50);
    let score = base.saturating_sub(base.saturating_mul(decay) / 100);
    score.min(100)
}

fn get_arbiter_record(account_hash_str: &str) -> ArbiterRecord {
    let arbiters_uref = get_dict_uref(ARBITERS_DICT);
    storage::dictionary_get(arbiters_uref, account_hash_str)
        .unwrap_or_revert()
        .unwrap_or_else(|| runtime::revert(ApiError::User(ERR_ARBITER_NOT_FOUND)))
}

fn get_election_record(dispute_id: &str) -> ElectionRecord {
    let elections_uref = get_dict_uref(ELECTIONS_DICT);
    storage::dictionary_get(elections_uref, dispute_id)
        .unwrap_or_revert()
        .unwrap_or_else(|| runtime::revert(ApiError::User(ERR_ELECTION_NOT_FOUND)))
}

fn get_active_arbiters_list() -> Vec<String> {
    let uref = runtime::get_key(ACTIVE_ARBITERS_LIST)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    storage::read::<Vec<String>>(uref)
        .unwrap_or_revert()
        .unwrap_or_default()
}

fn update_active_arbiters_list(list: Vec<String>) {
    let uref = runtime::get_key(ACTIVE_ARBITERS_LIST)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    storage::write(uref, list);
}

// Helper to get a random u64 from a seed
fn get_random_u64(seed: &[u8]) -> u64 {
    let hash = runtime::blake2b(seed);
    u64::from_le_bytes([
        hash[0], hash[1], hash[2], hash[3],
        hash[4], hash[5], hash[6], hash[7]
    ])
}

// Select `count` arbiters from the active list (may pick duplicates if list is small and count is large)
fn select_arbiters_from_list(
    active_arbiters: &[String],
    base_seed_input: &str,
    count: u64,
) -> Vec<String> {
    if active_arbiters.is_empty() || count == 0 {
        return Vec::new();
    }
    if count as usize > active_arbiters.len() {
        runtime::revert(ApiError::User(ERR_INSUFFICIENT_ARBITERS));
    }

    let mut selected_arbiters = Vec::new();
    for i in 0..count {
        let seed_for_this_selection = format!("{}{}", base_seed_input, i);
        let hash_val = get_random_u64(seed_for_this_selection.as_bytes());
        let index = (hash_val % active_arbiters.len() as u64) as usize;
        selected_arbiters.push(active_arbiters[index].clone());
    }
    selected_arbiters
}

#[no_mangle]
pub extern "C" fn register_arbiter() {
    let arbiter_account: AccountHash = runtime::get_named_arg("account");
    let stake: U512 = runtime::get_named_arg("stake");

    if stake == U512::zero() {
        runtime::revert(ApiError::User(ERR_INVALID_STAKE));
    }

    let arbiter_account_str = arbiter_account.to_string();
    let arbiters_uref = get_dict_uref(ARBITERS_DICT);

    if storage::dictionary_get::<ArbiterRecord>(arbiters_uref, &arbiter_account_str)
        .unwrap_or_revert()
        .is_some()
    {
        runtime::revert(ApiError::User(ERR_ARBITER_EXISTS));
    }

    // Transfer stake to the contract's stake purse
    let source_purse: URef = runtime::get_named_arg("source_purse");
    let stake_purse: URef = runtime::get_key(STAKE_PURSE)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    system::transfer_from_purse_to_purse(source_purse, stake_purse, stake, None).unwrap_or_revert();

    let block_time: u64 = runtime::get_blocktime().into();
    let record: ArbiterRecord = (
        (arbiter_account_str.clone(), stake, block_time),
        (0u64, 0u64, block_time),
        (true, DEFAULT_REPUTATION_SCORE, U512::zero()),
    );

    storage::dictionary_put(arbiters_uref, &arbiter_account_str, record);

    // Add to active arbiters list
    let mut active_arbiters = get_active_arbiters_list();
    active_arbiters.push(arbiter_account_str);
    update_active_arbiters_list(active_arbiters);
}

#[no_mangle]
pub extern "C" fn select_arbiters() {
    let dispute_id: String = runtime::get_named_arg("dispute_id");
    let count: u64 = runtime::get_named_arg("count");

    let elections_uref = get_dict_uref(ELECTIONS_DICT);

    if storage::dictionary_get::<ElectionRecord>(elections_uref, &dispute_id)
        .unwrap_or_revert()
        .is_some()
    {
        runtime::revert(ApiError::User(ERR_ELECTION_EXISTS));
    }

    let block_time: u64 = runtime::get_blocktime().into();
    let nonce = read_nonce();
    increment_nonce();

    let base_seed_input = format!("{}{}{}", block_time, dispute_id, nonce);

    let active_arbiters = get_active_arbiters_list();
    let selected_arbiters = select_arbiters_from_list(&active_arbiters, &base_seed_input, count);

    let selected_arbiters_csv = selected_arbiters.join(",");

    let record: ElectionRecord = (
        (dispute_id.clone(), base_seed_input, count),
        (selected_arbiters_csv, 0u64, 0u64), // Status 0 = Pending
    );

    storage::dictionary_put(elections_uref, &dispute_id, record);
}

#[no_mangle]
pub extern "C" fn submit_vote() {
    let dispute_id: String = runtime::get_named_arg("dispute_id");
    let vote: u64 = runtime::get_named_arg("vote");
    let evidence: String = runtime::get_named_arg("evidence");

    let caller = runtime::get_caller();
    let caller_str = caller.to_string();

    let election = get_election_record(&dispute_id);
    if (election.1).1 != 0u64 {
        // Check if election is already resolved
        runtime::revert(ApiError::User(ERR_ELECTION_RESOLVED));
    }

    let selected_arbiters_csv = (election.1).0;
    let selected_arbiters: Vec<String> = selected_arbiters_csv
        .split(',')
        .map(|s| s.to_string())
        .collect();

    if !selected_arbiters.contains(&caller_str) {
        runtime::revert(ApiError::User(ERR_NOT_SELECTED_ARBITER));
    }

    let votes_uref = get_dict_uref(VOTES_DICT);
    let vote_key = format!("{}_{}", dispute_id, caller_str);

    if storage::dictionary_get::<VoteRecord>(votes_uref, &vote_key)
        .unwrap_or_revert()
        .is_some()
    {
        runtime::revert(ApiError::User(ERR_ALREADY_VOTED));
    }

    let block_time: u64 = runtime::get_blocktime().into();
    let vote_record: VoteRecord = (
        (dispute_id.clone(), caller_str, vote),
        (evidence, block_time),
    );
    storage::dictionary_put(votes_uref, &vote_key, vote_record);
}

#[no_mangle]
pub extern "C" fn remove_arbiter() {
    assert_installer();

    let arbiter_account: AccountHash = runtime::get_named_arg("account");
    let arbiter_account_str = arbiter_account.to_string();

    let arbiters_uref = get_dict_uref(ARBITERS_DICT);
    let mut record = get_arbiter_record(&arbiter_account_str);

    // Set is_active to false
    record.2 .0 = false;

    storage::dictionary_put(arbiters_uref, &arbiter_account_str, record);

    // Remove from active arbiters list
    let mut active_arbiters = get_active_arbiters_list();
    active_arbiters.retain(|s| s != &arbiter_account_str);
    update_active_arbiters_list(active_arbiters);
}

#[no_mangle]
pub extern "C" fn configure_price() {
    assert_installer();

    let new_price_bps: u64 = runtime::get_named_arg("new_price_bps");
    let price_bps_uref = runtime::get_key(PRICE_BPS_KEY)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    storage::write(price_bps_uref, new_price_bps);
}

#[no_mangle]
pub extern "C" fn get_arbiter() {
    let arbiter_account: AccountHash = runtime::get_named_arg("account");
    let arbiter_account_str = arbiter_account.to_string();
    let record = get_arbiter_record(&arbiter_account_str);
    runtime::ret(CLValue::from_t(record).unwrap_or_revert());
}

#[no_mangle]
pub extern "C" fn get_selection() {
    let dispute_id: String = runtime::get_named_arg("dispute_id");
    let record = get_election_record(&dispute_id);
    runtime::ret(CLValue::from_t(record).unwrap_or_revert());
}

#[no_mangle]
pub extern "C" fn get_vote() {
    let dispute_id: String = runtime::get_named_arg("dispute_id");
    let arbiter_account: AccountHash = runtime::get_named_arg("arbiter_account");
    let arbiter_account_str = arbiter_account.to_string();

    let votes_uref = get_dict_uref(VOTES_DICT);
    let vote_key = format!("{}_{}", dispute_id, arbiter_account_str);

    let record: VoteRecord = storage::dictionary_get(votes_uref, &vote_key)
        .unwrap_or_revert()
        .unwrap_or_else(|| runtime::revert(ApiError::User(ERR_ARBITER_NOT_FOUND))); // Reusing error code

    runtime::ret(CLValue::from_t(record).unwrap_or_revert());
}

#[no_mangle]
pub extern "C" fn call() {
    let installer = runtime::get_caller();

    let arbiters_dict = storage::new_dictionary(ARBITERS_DICT).unwrap_or_revert();
    let elections_dict = storage::new_dictionary(ELECTIONS_DICT).unwrap_or_revert();
    let votes_dict = storage::new_dictionary(VOTES_DICT).unwrap_or_revert();
    let nonce_uref = storage::new_uref(0u64);
    let active_arbiters_list_uref = storage::new_uref(Vec::<String>::new());
    let contract_purse = system::create_purse();
    let stake_purse = system::create_purse();
    let price_bps_uref = storage::new_uref(DEFAULT_PRICE_BPS);

    let mut named_keys = NamedKeys::new();
    named_keys.insert(ARBITERS_DICT.into(), arbiters_dict.into());
    named_keys.insert(ELECTIONS_DICT.into(), elections_dict.into());
    named_keys.insert(VOTES_DICT.into(), votes_dict.into());
    named_keys.insert(NONCE_KEY.into(), nonce_uref.into());
    named_keys.insert(ACTIVE_ARBITERS_LIST.into(), active_arbiters_list_uref.into());
    named_keys.insert(CONTRACT_PURSE.into(), contract_purse.into());
    named_keys.insert(STAKE_PURSE.into(), stake_purse.into());
    named_keys.insert(PRICE_BPS_KEY.into(), price_bps_uref.into());
    named_keys.insert(INSTALLER_KEY.into(), Key::Account(installer));

    let mut entry_points = EntryPoints::new();

    entry_points.add_entry_point(EntityEntryPoint::new(
        "register_arbiter",
        vec![
            Parameter::new("account", CLType::Key),
            Parameter::new("stake", CLType::U512),
            Parameter::new("source_purse", CLType::URef),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "select_arbiters",
        vec![
            Parameter::new("dispute_id", CLType::String),
            Parameter::new("count", CLType::U64),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "submit_vote",
        vec![
            Parameter::new("dispute_id", CLType::String),
            Parameter::new("vote", CLType::U64),
            Parameter::new("evidence", CLType::String),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "remove_arbiter",
        vec![Parameter::new("account", CLType::Key)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "configure_price",
        vec![Parameter::new("new_price_bps", CLType::U64)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "get_arbiter",
        vec![Parameter::new("account", CLType::Key)],
        CLType::Any,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "get_selection",
        vec![Parameter::new("dispute_id", CLType::String)],
        CLType::Any,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "get_vote",
        vec![
            Parameter::new("dispute_id", CLType::String),
            Parameter::new("arbiter_account", CLType::Key),
        ],
        CLType::Any,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    let (contract_hash, _) = storage::new_contract(
        entry_points,
        Some(named_keys),
        Some("vrf_arbiter_package_hash".into()),
        Some("vrf_arbiter_access_uref".into()),
        None,
    );
    runtime::put_key("vrf_arbiter_contract", contract_hash.into());
}