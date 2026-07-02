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
    ApiError, CLType, CLValue, EntityEntryPoint, EntryPointAccess, EntryPointType, EntryPoints, Key,
    Parameter, URef, U512, EntryPointPayment,
};

// Error codes
const ERROR_NOT_INSTALLER: u16 = 1;
const ERROR_ESCROW_NOT_FOUND: u16 = 2;
const ERROR_NOT_SENDER: u16 = 3;
const ERROR_INVALID_STATUS: u16 = 4;
const ERROR_ALREADY_EXISTS: u16 = 5;
const ERROR_INVALID_FEE: u16 = 6;
const ERROR_TRANSFER_FAILED: u16 = 7;
const ERROR_INVALID_TTL: u16 = 8;
const ERROR_ESCROW_EXPIRED: u16 = 9;
const ERROR_INVALID_AMOUNT: u16 = 10;
const ERROR_INVALID_ACCOUNT_HASH: u16 = 11;
const ERROR_INPUT_MISMATCH: u16 = 12;
const ERROR_BATCH_LIMIT_EXCEEDED: u16 = 13;

// Storage keys
const INSTALLER_KEY: &str = "installer";
const ESCROWS_DICT: &str = "escrows_dict";
const FEE_BPS_KEY: &str = "fee_bps";
const CONTRACT_PURSE_KEY: &str = "contract_purse"; // Main purse for holding escrow funds
const FEE_PURSE_KEY: &str = "fee_purse"; // Purse for collecting fees
const ALL_ESCROW_KEYS: &str = "all_escrow_keys"; // List of all service_hashes for listing

// Status constants
const STATUS_PENDING: u64 = 0;
const STATUS_RELEASED: u64 = 1;
const STATUS_CANCELLED: u64 = 2;
const STATUS_DISPUTED: u64 = 3; // Not used in this version, but kept for consistency
const STATUS_RESOLVED: u64 = 4; // Not used in this version, but kept for consistency
const STATUS_EXPIRED: u64 = 5;

// Max fee in basis points (1000 = 10%)
const MAX_FEE_BPS: u64 = 1000;
const MAX_BATCH_SIZE: usize = 50; // Limit for batch operations

/// Escrow record layout: ((sender, receiver, amount), (fee_bps, ttl, status), (created_at, evidence_hash))
/// service_hash is the dictionary key.
type EscrowRecord = ((String, String, U512), (u64, u64, u64), (u64, String));

// Helper functions

fn get_installer() -> AccountHash {
    let key: Key = runtime::get_key(INSTALLER_KEY)
        .unwrap_or_revert_with(ApiError::User(ERROR_ESCROW_NOT_FOUND));
    key.into_account()
        .unwrap_or_revert_with(ApiError::User(ERROR_INVALID_ACCOUNT_HASH))
}

fn check_installer() {
    let caller = runtime::get_caller();
    let installer = get_installer();
    if caller != installer {
        runtime::revert(ApiError::User(ERROR_NOT_INSTALLER));
    }
}

fn get_escrows_dict_uref() -> URef {
    runtime::get_key(ESCROWS_DICT)
        .unwrap_or_revert_with(ApiError::User(ERROR_ESCROW_NOT_FOUND))
        .into_uref()
        .unwrap_or_revert()
}

fn get_contract_purse_uref() -> URef {
    runtime::get_key(CONTRACT_PURSE_KEY)
        .unwrap_or_revert_with(ApiError::User(ERROR_ESCROW_NOT_FOUND))
        .into_uref()
        .unwrap_or_revert()
}

fn get_fee_purse_uref() -> URef {
    runtime::get_key(FEE_PURSE_KEY)
        .unwrap_or_revert_with(ApiError::User(ERROR_ESCROW_NOT_FOUND))
        .into_uref()
        .unwrap_or_revert()
}

fn get_all_escrow_keys_uref() -> URef {
    runtime::get_key(ALL_ESCROW_KEYS)
        .unwrap_or_revert_with(ApiError::User(ERROR_ESCROW_NOT_FOUND))
        .into_uref()
        .unwrap_or_revert()
}

fn read_fee_bps() -> u64 {
    let uref = runtime::get_key(FEE_BPS_KEY)
        .unwrap_or_revert_with(ApiError::User(ERROR_ESCROW_NOT_FOUND))
        .into_uref()
        .unwrap_or_revert();
    storage::read::<u64>(uref)
        .unwrap_or_revert()
        .unwrap_or(0) // Default fee is 0
}

fn store_escrow(
    service_hash: &str,
    sender: &str,
    receiver: &str,
    amount: U512,
    fee_bps: u64,
    ttl: u64,
    status: u64,
    created_at: u64,
    evidence_hash: &str,
) {
    let dict_uref = get_escrows_dict_uref();

    let record: EscrowRecord = (
        (sender.to_string(), receiver.to_string(), amount),
        (fee_bps, ttl, status),
        (created_at, evidence_hash.to_string()),
    );

    storage::dictionary_put(dict_uref, service_hash, record);
}

fn get_escrow_record(service_hash: &str) -> Option<EscrowRecord> {
    let dict_uref = get_escrows_dict_uref();
    storage::dictionary_get(dict_uref, service_hash)
        .unwrap_or_revert()
}

fn update_escrow_status(service_hash: &str, new_status: u64) {
    let record = get_escrow_record(service_hash)
        .unwrap_or_revert_with(ApiError::User(ERROR_ESCROW_NOT_FOUND));

    let ((sender, receiver, amount), (fee_bps, ttl, _old_status), (created_at, evidence_hash)) = record;

    store_escrow(
        service_hash,
        &sender,
        &receiver,
        amount,
        fee_bps,
        ttl,
        new_status,
        created_at,
        &evidence_hash,
    );
}

// Entry points

#[no_mangle]
pub extern "C" fn create_batch() {
    let count: u32 = runtime::get_named_arg("count");
    let receivers_str: Vec<String> = runtime::get_named_arg("receivers");
    let amounts: Vec<U512> = runtime::get_named_arg("amounts");
    let service_hashes: Vec<String> = runtime::get_named_arg("service_hashes");
    let ttls: Vec<u64> = runtime::get_named_arg("ttls");
    let source_purse: URef = runtime::get_named_arg("source_purse");

    let caller = runtime::get_caller();
    let contract_purse = get_contract_purse_uref();
    let current_fee_bps = read_fee_bps();
    let created_at: u64 = runtime::get_blocktime().into();

    if count == 0 {
        runtime::revert(ApiError::User(ERROR_INPUT_MISMATCH));
    }
    if count as usize > MAX_BATCH_SIZE {
        runtime::revert(ApiError::User(ERROR_BATCH_LIMIT_EXCEEDED));
    }

    if receivers_str.len() != count as usize
        || amounts.len() != count as usize
        || service_hashes.len() != count as usize
        || ttls.len() != count as usize
    {
        runtime::revert(ApiError::User(ERROR_INPUT_MISMATCH));
    }

    let all_keys_uref = get_all_escrow_keys_uref();
    let mut current_all_service_hashes: Vec<String> = storage::read(all_keys_uref)
        .unwrap_or_revert()
        .unwrap_or_default();

    let mut created_service_hashes = Vec::new();

    for i in 0..count as usize {
        let receiver_str = &receivers_str[i];
        let amount = amounts[i];
        let service_hash = &service_hashes[i];
        let ttl = ttls[i];

        if amount.is_zero() {
            runtime::revert(ApiError::User(ERROR_INVALID_AMOUNT));
        }
        if ttl == 0 {
            runtime::revert(ApiError::User(ERROR_INVALID_TTL));
        }

        // Check if service_hash already exists
        if get_escrow_record(service_hash).is_some() {
            runtime::revert(ApiError::User(ERROR_ALREADY_EXISTS));
        }

        // Transfer funds from source_purse to contract_purse
        system::transfer_from_purse_to_purse(source_purse, contract_purse, amount, None)
            .unwrap_or_revert_with(ApiError::User(ERROR_TRANSFER_FAILED));

        store_escrow(
            service_hash,
            &caller.to_string(), // Sender is the caller
            receiver_str,
            amount,
            current_fee_bps,
            ttl,
            STATUS_PENDING,
            created_at,
            "", // No evidence hash initially
        );
        current_all_service_hashes.push(service_hash.clone());
        created_service_hashes.push(service_hash.clone());
    }

    storage::write(all_keys_uref, current_all_service_hashes);
    runtime::ret(CLValue::from_t(created_service_hashes).unwrap_or_revert());
}

#[no_mangle]
pub extern "C" fn batch_release() {
    let service_hashes: Vec<String> = runtime::get_named_arg("service_hashes");
    let caller = runtime::get_caller();
    let contract_purse = get_contract_purse_uref();
    let fee_purse = get_fee_purse_uref();

    if service_hashes.is_empty() {
        runtime::revert(ApiError::User(ERROR_INPUT_MISMATCH));
    }
    if service_hashes.len() > MAX_BATCH_SIZE {
        runtime::revert(ApiError::User(ERROR_BATCH_LIMIT_EXCEEDED));
    }

    for service_hash in service_hashes {
        let record = get_escrow_record(&service_hash)
            .unwrap_or_revert_with(ApiError::User(ERROR_ESCROW_NOT_FOUND));

        let ((sender_str, receiver_str, amount), (fee_bps, ttl, status), (created_at, _evidence_hash)) = record;

        let sender_account = AccountHash::from_formatted_str(&sender_str)
            .map_err(|_| ApiError::User(ERROR_INVALID_ACCOUNT_HASH))
            .unwrap_or_revert();
        let receiver_account = AccountHash::from_formatted_str(&receiver_str)
            .map_err(|_| ApiError::User(ERROR_INVALID_ACCOUNT_HASH))
            .unwrap_or_revert();

        // Only sender can release
        if caller != sender_account {
            runtime::revert(ApiError::User(ERROR_NOT_SENDER));
        }

        if status != STATUS_PENDING {
            runtime::revert(ApiError::User(ERROR_INVALID_STATUS));
        }

        let current_time: u64 = runtime::get_blocktime().into();
        if current_time > created_at + ttl {
            update_escrow_status(&service_hash, STATUS_EXPIRED);
            runtime::revert(ApiError::User(ERROR_ESCROW_EXPIRED));
        }

        let fee_amount = amount.checked_mul(U512::from(fee_bps))
            .unwrap_or_revert_with(ApiError::User(100))
            .checked_div(U512::from(10000))
            .unwrap_or_revert_with(ApiError::User(100));
        let receiver_amount = amount.checked_sub(fee_amount)
            .unwrap_or_revert_with(ApiError::User(100));

        if fee_amount > U512::zero() {
            system::transfer_from_purse_to_purse(contract_purse, fee_purse, fee_amount, None)
                .unwrap_or_revert_with(ApiError::User(ERROR_TRANSFER_FAILED));
        }

        system::transfer_from_purse_to_account(contract_purse, receiver_account, receiver_amount, None)
            .unwrap_or_revert_with(ApiError::User(ERROR_TRANSFER_FAILED));

        update_escrow_status(&service_hash, STATUS_RELEASED);
    }
}

#[no_mangle]
pub extern "C" fn batch_cancel() {
    let service_hashes: Vec<String> = runtime::get_named_arg("service_hashes");
    let caller = runtime::get_caller();
    let contract_purse = get_contract_purse_uref();

    if service_hashes.is_empty() {
        runtime::revert(ApiError::User(ERROR_INPUT_MISMATCH));
    }
    if service_hashes.len() > MAX_BATCH_SIZE {
        runtime::revert(ApiError::User(ERROR_BATCH_LIMIT_EXCEEDED));
    }

    for service_hash in service_hashes {
        let record = get_escrow_record(&service_hash)
            .unwrap_or_revert_with(ApiError::User(ERROR_ESCROW_NOT_FOUND));

        let ((sender_str, _receiver_str, amount), (_fee_bps, _ttl, status), (_created_at, _evidence_hash)) = record;

        let sender_account = AccountHash::from_formatted_str(&sender_str)
            .map_err(|_| ApiError::User(ERROR_INVALID_ACCOUNT_HASH))
            .unwrap_or_revert();

        // Only sender can cancel
        if caller != sender_account {
            runtime::revert(ApiError::User(ERROR_NOT_SENDER));
        }

        if status != STATUS_PENDING {
            runtime::revert(ApiError::User(ERROR_INVALID_STATUS));
        }

        system::transfer_from_purse_to_account(contract_purse, sender_account, amount, None)
            .unwrap_or_revert_with(ApiError::User(ERROR_TRANSFER_FAILED));

        update_escrow_status(&service_hash, STATUS_CANCELLED);
    }
}

#[no_mangle]
pub extern "C" fn list_escrows() {
    let offset: u32 = runtime::get_named_arg("offset");
    let limit: u32 = runtime::get_named_arg("limit");

    let all_keys_uref = get_all_escrow_keys_uref();
    let all_service_hashes: Vec<String> = storage::read(all_keys_uref)
        .unwrap_or_revert()
        .unwrap_or_default();

    let start_index = offset as usize;
    let end_index = (offset + limit) as usize;

    if start_index >= all_service_hashes.len() {
        runtime::ret(CLValue::from_t(Vec::<EscrowRecord>::new()).unwrap_or_revert());
        return;
    }

    let actual_end_index = all_service_hashes.len().min(end_index);
    let mut result_escrows = Vec::new();

    for i in start_index..actual_end_index {
        let service_hash = &all_service_hashes[i];
        if let Some(record) = get_escrow_record(service_hash) {
            result_escrows.push(record);
        }
    }

    runtime::ret(CLValue::from_t(result_escrows).unwrap_or_revert());
}

#[no_mangle]
pub extern "C" fn set_fee() {
    check_installer();

    let new_fee_bps: u64 = runtime::get_named_arg("new_fee_bps");
    if new_fee_bps > MAX_FEE_BPS {
        runtime::revert(ApiError::User(ERROR_INVALID_FEE));
    }

    let fee_uref = runtime::get_key(FEE_BPS_KEY)
        .unwrap_or_revert_with(ApiError::User(ERROR_ESCROW_NOT_FOUND))
        .into_uref()
        .unwrap_or_revert();

    storage::write(fee_uref, new_fee_bps);
}

fn get_entry_points() -> EntryPoints {
    let mut entry_points = EntryPoints::new();

    entry_points.add_entry_point(EntityEntryPoint::new(
        "create_batch",
        vec![
            Parameter::new("count", CLType::U32),
            Parameter::new("receivers", CLType::List(Box::new(CLType::String))),
            Parameter::new("amounts", CLType::List(Box::new(CLType::U512))),
            Parameter::new("service_hashes", CLType::List(Box::new(CLType::String))),
            Parameter::new("ttls", CLType::List(Box::new(CLType::U64))),
            Parameter::new("source_purse", CLType::URef),
        ],
        CLType::List(Box::new(CLType::String)), // Returns list of created service_hashes
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "batch_release",
        vec![Parameter::new("service_hashes", CLType::List(Box::new(CLType::String)))],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "batch_cancel",
        vec![Parameter::new("service_hashes", CLType::List(Box::new(CLType::String)))],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "list_escrows",
        vec![
            Parameter::new("offset", CLType::U32),
            Parameter::new("limit", CLType::U32),
        ],
        CLType::Any,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "set_fee",
        vec![Parameter::new("new_fee_bps", CLType::U64)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points
}

#[no_mangle]
pub extern "C" fn call() {
    let installer = runtime::get_caller();

    let escrows_dict = storage::new_dictionary(ESCROWS_DICT).unwrap_or_revert();
    let contract_purse = system::create_purse();
    let fee_purse = system::create_purse();
    let fee_bps_uref = storage::new_uref(0u64); // Default fee_bps is 0
    let all_escrow_keys_uref = storage::new_uref(Vec::<String>::new()); // To support list_escrows

    let mut named_keys = NamedKeys::new();
    named_keys.insert(INSTALLER_KEY.into(), Key::Account(installer));
    named_keys.insert(ESCROWS_DICT.into(), escrows_dict.into());
    named_keys.insert(CONTRACT_PURSE_KEY.into(), contract_purse.into());
    named_keys.insert(FEE_PURSE_KEY.into(), fee_purse.into());
    named_keys.insert(FEE_BPS_KEY.into(), fee_bps_uref.into());
    named_keys.insert(ALL_ESCROW_KEYS.into(), all_escrow_keys_uref.into());

    let entry_points = get_entry_points();

    let (contract_hash, _version) = storage::new_contract(
        entry_points,
        Some(named_keys),
        Some("escrow_manager_package_hash".into()),
        Some("escrow_manager_access_uref".into()),
        None,
    );
    runtime::put_key("escrow_manager_contract_hash", contract_hash.into());
}
