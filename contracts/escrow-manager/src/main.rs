#![no_std]
#![no_main]

extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;
use alloc::vec;

use casper_contract::contract_api::{runtime, storage, system};
use casper_contract::unwrap_or_revert::UnwrapOrRevert;

use casper_types::{
    ApiError, CLType, CLValue, EntityEntryPoint, EntryPointAccess, EntryPointType, EntryPoints,
    Parameter, URef, U512, Key,
};
use casper_types::account::AccountHash;
use casper_types::contracts::NamedKeys;
use casper_types::EntryPointPayment;

// Error codes
const ERROR_NOT_INSTALLER: u16 = 1;
const ERROR_ESCROW_NOT_FOUND: u16 = 2;
const ERROR_NOT_SENDER: u16 = 3;
const ERROR_NOT_RECEIVER: u16 = 4;
const ERROR_INVALID_STATUS: u16 = 5;
const ERROR_ALREADY_EXISTS: u16 = 6;
const ERROR_INVALID_FEE: u16 = 7;
const ERROR_CONTRACT_FROZEN: u16 = 8;
const ERROR_TRANSFER_FAILED: u16 = 9;
const ERROR_INVALID_TTL: u16 = 10;
const ERROR_ESCROW_EXPIRED: u16 = 11;
const ERROR_INVALID_AMOUNT: u16 = 12;
const ERROR_NOT_PARTICIPANT: u16 = 13;

// Storage keys
const KEY_INSTALLER: &str = "installer";
const KEY_ESCROWS: &str = "escrows";
const KEY_ESCROW_COUNTER: &str = "escrow_counter";
const KEY_FEE_BPS: &str = "fee_bps";
const KEY_FROZEN: &str = "frozen";
const KEY_FEE_PURSE: &str = "fee_purse";
const KEY_ESCROW_DICT: &str = "escrow_dict";

// Status constants
const STATUS_PENDING: u64 = 0;
const STATUS_RELEASED: u64 = 1;
const STATUS_CANCELLED: u64 = 2;
const STATUS_DISPUTED: u64 = 3;
const STATUS_RESOLVED: u64 = 4;
const STATUS_EXPIRED: u64 = 5;

// Max fee in basis points (1000 = 10%)
const MAX_FEE_BPS: u64 = 1000;

fn get_installer() -> AccountHash {
    let key: Key = runtime::get_key(KEY_INSTALLER)
        .unwrap_or_revert_with(ApiError::User(ERROR_ESCROW_NOT_FOUND))
        .into();
    key.into_account()
        .unwrap_or_revert_with(ApiError::User(ERROR_ESCROW_NOT_FOUND))
}

fn check_installer() {
    let caller = runtime::get_caller();
    let installer = get_installer();
    if caller != installer {
        runtime::revert(ApiError::User(ERROR_NOT_INSTALLER));
    }
}

fn check_not_frozen() {
    let frozen: bool = storage::read(runtime::get_key(KEY_FROZEN).unwrap_or_revert().into_uref().unwrap_or_revert())
        .unwrap_or(Some(false))
        .unwrap_or(false);
    if frozen {
        runtime::revert(ApiError::User(ERROR_CONTRACT_FROZEN));
    }
}

fn get_escrow_dict_uref() -> URef {
    runtime::get_key(KEY_ESCROW_DICT)
        .unwrap_or_revert_with(ApiError::User(ERROR_ESCROW_NOT_FOUND))
        .into_uref()
        .unwrap_or_revert()
}

fn get_next_escrow_id() -> String {
    let counter_uref = runtime::get_key(KEY_ESCROW_COUNTER)
        .unwrap_or_revert_with(ApiError::User(ERROR_ESCROW_NOT_FOUND))
        .into_uref()
        .unwrap_or_revert();
    
    let current: u64 = storage::read(counter_uref)
        .unwrap_or(Some(0))
        .unwrap_or(0);
    
    let next = current + 1;
    storage::write(counter_uref, next);
    
    format!("escrow_{}", next)
}

fn store_escrow(
    escrow_id: &str,
    sender: &str,
    receiver: &str,
    amount: u64,
    fee_bps: u64,
    ttl: u64,
    status: u64,
    created_at: u64,
    evidence_hash: &str,
    service_hash: &str,
) {
    let dict_uref = get_escrow_dict_uref();
    
    let record = (
        (escrow_id.to_string(), sender.to_string(), receiver.to_string()),
        (amount, fee_bps, ttl),
        (status, created_at, evidence_hash.to_string()),
        service_hash.to_string(),
    );
    
    storage::dictionary_put(dict_uref, escrow_id, record);
}

fn get_escrow_record(escrow_id: &str) -> Option<(
    (String, String, String),
    (u64, u64, u64),
    (u64, u64, String),
    String,
)> {
    let dict_uref = get_escrow_dict_uref();
    storage::dictionary_get(dict_uref, escrow_id)
        .unwrap_or(None)
}

fn update_escrow_status(escrow_id: &str, new_status: u64) {
    let record = get_escrow_record(escrow_id)
        .unwrap_or_revert_with(ApiError::User(ERROR_ESCROW_NOT_FOUND));
    
    let ((id, sender, receiver), (amount, fee_bps, ttl), (_, created_at, evidence_hash), service_hash) = record;
    
    store_escrow(
        &id,
        &sender,
        &receiver,
        amount,
        fee_bps,
        ttl,
        new_status,
        created_at,
        &evidence_hash,
        &service_hash,
    );
}

fn get_fee_purse() -> URef {
    runtime::get_key(KEY_FEE_PURSE)
        .unwrap_or_revert_with(ApiError::User(ERROR_ESCROW_NOT_FOUND))
        .into_uref()
        .unwrap_or_revert()
}

#[no_mangle]
pub extern "C" fn create_escrow() {
    check_not_frozen();
    
    let sender = runtime::get_named_arg::<String>("sender");
    let receiver = runtime::get_named_arg::<String>("receiver");
    let amount: u64 = runtime::get_named_arg("amount");
    let ttl: u64 = runtime::get_named_arg("ttl");
    let service_hash = runtime::get_named_arg::<String>("service_hash");
    let fee_bps: u64 = runtime::get_named_arg("fee_bps");
    
    if amount == 0 {
        runtime::revert(ApiError::User(ERROR_INVALID_AMOUNT));
    }
    
    if ttl == 0 {
        runtime:: upsilon_revert(ApiError::User(ERROR_INVALID_TTL));
    }
    
    if fee_bps > MAX_FEE_BPS {
        runtime::revert(ApiError::User(ERROR_INVALID_FEE));
    }
    
    let caller = runtime::get_caller();
    let sender_account = AccountHash::from_formatted_str(&sender)
        .unwrap_or_revert_with(ApiError::User(ERROR_INVALID_STATUS));
    
    if caller != sender_account {
        runtime::revert(ApiError::User(ERROR_NOT_SENDER));
    }
    
    let escrow_id = get_next_escrow_id();
    
    if get_escrow_record(&escrow_id).is_some() {
        runtime::revert(ApiError::User(ERROR_ALREADY_EXISTS));
    }
    
    let main_purse = system::get_main_purse();
    let contract_purse = system::create_purse();
    
    let transfer_amount = U512::from(amount);
    system::transfer_from_purse_to_purse(main_purse, contract_purse, transfer_amount, None)
        .unwrap_or_revert_with(ApiError::User(ERROR_TRANSFER_FAILED));
    
    let created_at = runtime::get_blocktime().into();
    
    store_escrow(
        &escrow_id,
        &sender,
        &receiver,
        amount,
        fee_bps,
        ttl,
        STATUS_PENDING,
        created_at,
        "",
        &service_hash,
    );
    
    let result = CLValue::from_t((escrow_id,)).unwrap_or_revert();
    runtime::ret(result);
}

#[no_mangle]
pub extern "C" fn release_escrow() {
    check_not_frozen();
    
    let escrow_id = runtime::get_named_arg::<String>("escrow_id");
    let record = get_escrow_record(&escrow_id)
        .unwrap_or_revert_with(ApiError::User(ERROR_ESCROW_NOT_FOUND));
    
    let ((id, sender_str, receiver_str), (amount, fee_bps, ttl), (status, created_at, evidence_hash), service_hash) = record;
    
    let caller = runtime::get_caller();
    let sender_account = AccountHash::from_formatted_str(&sender_str)
        .unwrap_or_revert_with(ApiError::User(ERROR_INVALID_STATUS));
    
    if caller != sender_account {
        runtime::revert(ApiError::User(ERROR_NOT_SENDER));
    }
    
    if status != STATUS_PENDING {
        runtime::revert(ApiError::User(ERROR_INVALID_STATUS));
    }
    
    let current_time: u64 = runtime::get_blocktime().into();
    if current_time > created_at + ttl {
        update_escrow_status(&escrow_id, STATUS_EXPIRED);
        runtime::revert(ApiError::User(ERROR_ESCROW_EXPIRED));
    }
    
    let fee_amount = (amount * fee_bps) / 10000;
    let receiver_amount = amount - fee_amount;
    
    let contract_purse = system::create_purse();
    let fee_purse = get_fee_purse();
    let receiver = AccountHash::from_formatted_str(&receiver_str)
        .unwrap_or_revert_with(ApiError::User(ERROR_INVALID_STATUS));
    
    if fee_amount > 0 {
        system::transfer_from_purse_to_purse(contract_purse, fee_purse, U512::from(fee_amount), None)
            .unwrap_or_revert_with(ApiError::User(ERROR_TRANSFER_FAILED));
    }
    
    system::transfer_from_purse_to_account(contract_purse, receiver, U512::from(receiver_amount), None)
        .unwrap_or_revert_with(ApiError::User(ERROR_TRANSFER_FAILED));
    
    update_escrow_status(&escrow_id, STATUS_RELEASED);
}

#[no_mangle]
pub extern "C" fn cancel_escrow() {
    check_not_frozen();
    
    let escrow_id = runtime::get_named_arg::<String>("escrow_id");
    let record = get_escrow_record(&escrow_id)
        .unwrap_or_revert_with(ApiError::User(ERROR_ESCROW_NOT_FOUND));
    
    let ((id, sender_str, receiver_str), (amount, fee_bps, ttl), (status, created_at, evidence_hash), service_hash) = record;
    
    let caller = runtime::get_caller();
    let sender_account = AccountHash::from_formatted_str(&sender_str)
        .unwrap_or_revert_with(ApiError::User(ERROR_INVALID_STATUS));
    
    if caller != sender_account {
        runtime::revert(ApiError::User(ERROR_NOT_SENDER));
    }
    
    if status != STATUS_PENDING {
        runtime::revert(ApiError::User(ERROR_INVALID_STATUS));
    }
    
    let contract_purse = system::create_purse();
    system::transfer_from_purse_to_account(contract_purse, sender_account, U512::from(amount), None)
        .unwrap_or_revert_with(ApiError::User(ERROR_TRANSFER_FAILED));
    
    update_escrow_status(&escrow_id, STATUS_CANCELLED);
}

#[no_mangle]
pub extern "C" fn dispute_escrow() {
    check_not_frozen();
    
    let escrow_id = runtime::get_named_arg::<String>("escrow_id");
    let evidence_hash = runtime::get_named_arg::<String>("evidence_hash");
    
    let record = get_escrow_record(&escrow_id)
        .unwrap_or_revert_with(ApiError::User(ERROR_ESCROW_NOT_FOUND));
    
    let ((id, sender_str, receiver_str), (amount, fee_bps, ttl), (status, created_at, old_evidence), service_hash) = record;
    
    let caller = runtime::get_caller();
    let sender_account = AccountHash::from_formatted_str(&sender_str)
        .unwrap_or_revert_with(ApiError::User(ERROR_INVALID_STATUS));
    let receiver_account = AccountHash::from_formatted_str(&receiver_str)
        .unwrap_or_revert_with(ApiError::User(ERROR_INVALID_STATUS));
    
    if caller != sender_account && caller != receiver_account {
        runtime::revert(ApiError::User(ERROR_NOT_PARTICIPANT));
    }
    
    if status != STATUS_PENDING {
        runtime::revert(ApiError::User(ERROR_INVALID_STATUS));
    }
    
    let dict_uref = get_escrow_dict_uref();
    let new_record = (
        (escrow_id.clone(), sender_str, receiver_str),
        (amount, fee_bps, ttl),
        (STATUS_DISPUTED, created_at, evidence_hash),
        service_hash,
    );
    storage::dictionary_put(dict_uref, &escrow_id, new_record);
}

#[no_mangle]
pub extern "C" fn resolve_dispute() {
    check_installer();
    check_not_frozen();
    
    let escrow_id = runtime::get_named_arg::<String>("escrow_id");
    let winner_str = runtime::get_named_arg::<String>("winner");
    
    let record = get_escrow_record(&escrow_id)
        .unwrap_or_revert_with(ApiError::User(ERROR_ESCROW_NOT_FOUND));
    
    let ((id, sender_str, receiver_str), (amount, fee_bps, ttl), (status, created_at, evidence_hash), service_hash) = record;
    
    if status != STATUS_DISPUTED {
        runtime::revert(ApiError::User(ERROR_INVALID_STATUS));
    }
    
    let winner = AccountHash::from_formatted_str(&winner_str)
        .unwrap_or_revert_with(ApiError::User(ERROR_INVALID_STATUS));
    
    let fee_amount = (amount * fee_bps) / 10000;
    let payout = amount - fee_amount;
    
    let contract_purse = system::create_purse();
    let fee_purse = get_fee_purse();
    
    if fee_amount > 0 {
        system::transfer_from_purse_to_purse(contract_purse, fee_purse, U512::from(fee_amount), None)
            .unwrap_or_revert_with(ApiError::User(ERROR_TRANSFER_FAILED));
    }
    
    system::transfer_from_purse_to_account(contract_purse, winner, U512::from(payout), None)
        .unwrap_or_revert_with(ApiError::User(ERROR_TRANSFER_FAILED));
    
    update_escrow_status(&escrow_id, STATUS_RESOLVED);
}

#[no_mangle]
pub extern "C" fn get_escrow() {
    let escrow_id = runtime::get_named_arg::<String>("escrow_id");
    let record = get_escrow_record(&escrow_id)
        .unwrap_or_revert_with(ApiError::User(ERROR_ESCROW_NOT_FOUND));
    
    let result = CLValue::from_t(record).unwrap_or_revert();
    runtime::ret(result);
}

#[no_mangle]
pub extern "C" fn set_fee() {
    check_installer();
    
    let new_fee_bps: u64 = runtime::get_named_arg("new_bps");
    if new_fee_bps > MAX_FEE_BPS {
        runtime::revert(ApiError::User(ERROR_INVALID_FEE));
    }
    
    let fee_uref = runtime::get_key(KEY_FEE_BPS)
        .unwrap_or_revert_with(ApiError::User(ERROR_ESCROW_NOT_FOUND))
        .into_uref()
        .unwrap_or_revert();
    
    storage::write(fee_uref, new_fee_bps);
}

#[no_mangle]
pub extern "C" fn freeze() {
    check_installer();
    
    let frozen_uref = runtime::get_key(KEY_FROZEN)
        .unwrap_or_revert_with(ApiError::User(ERROR_ESCROW_NOT_FOUND))
        .into_uref()
        .unwrap_or_revert();
    
    storage::write(frozen_uref, true);
}

#[no_mangle]
pub extern "C" fn unfreeze() {
    check_installer();
    
    let frozen_uref = runtime::get_key(KEY_FROZEN)
        .unwrap_or_revert_with(ApiError::User(ERROR_ESCROW_NOT_FOUND))
        .into_uref()
        .unwrap_or_revert();
    
    storage::write(frozen_uref, false);
}

fn get_entry_points() -> EntryPoints {
    let mut entry_points = EntryPoints::new();
    
    entry_points.add_entry_point(
        EntityEntryPoint::new(
            "create_escrow",
            vec![
                Parameter::new("sender", CLType::String),
                Parameter::new("receiver", CLType::String),
                Parameter::new("amount", CLType::U64),
                Parameter::new("ttl", CLType::U64),
                Parameter::new("service_hash", CLType::String),
                Parameter::new("fee_bps", CLType::U64),
            ],
            CLType::Tuple {
                elements: vec![Box::new(CLType::String)],
            },
            EntryPointAccess::Public,
            EntryPointType::Contract,
            EntryPointPayment::Caller,
        ),
    );
    
    entry_points.add_entry_point(
        EntityEntryPoint::new(
            "release_escrow",
            vec![Parameter::new("escrow_id", CLType::String)],
            CLType::Unit,
            EntryPointAccess::Public,
            EntryPointType::Contract,
            EntryPointPayment::Caller,
        ),
    );
    
    entry_points.add_entry_point(
        EntityEntryPoint::new(
            "cancel_escrow",
            vec![Parameter::new("escrow_id", CLType::String)],
            CLType::Unit,
            EntryPointAccess::Public,
            EntryPointType::Contract,
            EntryPointPayment::Caller,
        ),
    );
    
    entry_points.add_entry_point(
        EntityEntryPoint::new(
            "dispute_escrow",
            vec![
                Parameter::new("escrow_id", CLType::String),
                Parameter::new("evidence_hash", CLType::String),
            ],
            CLType::Unit,
            EntryPointAccess::Public,
            EntryPointType::Contract,
            EntryPointPayment::Caller,
        ),
    );
    
    entry_points.add_entry_point(
        EntityEntryPoint::new(
            "resolve_dispute",
            vec![
                Parameter::new("escrow_id", CLType::String),
                Parameter::new("winner", CLType::String),
            ],
            CLType::Unit,
            EntryPointAccess::Public,
            EntryPointType::Contract,
            EntryPointPayment::Caller,
        ),
    );
    
    entry_points.add_entry_point(
        EntityEntryPoint::new(
            "get_escrow",
            vec![Parameter::new("escrow_id", CLType::String)],
            CLType::Any,
            EntryPointAccess::Public,
            EntryPointType::Contract,
            EntryPointPayment::Caller,
        ),
    );
    
    entry_points.add_entry_point(
        EntityEntryPoint::new(
            "set_fee",
            vec![Parameter::new("new_bps", CLType::U64)],
            dependency_only::Unit,
            EntryPointAccess::Public,
            EntryPointType::Contract,
            EntryPointPayment::Caller,
        ),
    );
    
    entry_points.add_entry_point(
        EntityEntryPoint::new(
            "freeze",
            vec![],
            CLType::Unit,
            EntryPointAccess::Public,
            EntryPointType::Contract,
            EntryPointPayment::Caller,
        ),
    );
    
    entry_points.add_entry_point(
        EntityEntryPoint::new(
            "unfreeze",
            vec![],
            CLType::Unit,
            EntryPointAccess::Public,
            EntryPointType::Contract,
            EntryPointPayment::Caller,
        ),
    );
    
    entry_points
}

#[no_mangle]
pub extern "C" fn call() {
    let mut named_keys = NamedKeys::new();
    
    let installer = runtime::get_caller();
    named_keys.insert(KEY_INSTALLER.to_string(), installer.into());
    
    let escrow_counter_uref = storage::new_uref(0u64);
    named_keys.insert(KEY_ESCROW_COUNTER.to_string(), escrow_counter_uref.into());
    
    let fee_bps_uref = storage::new_uref(0u64);
    named_keys.insert(KEY_FEE_BPS.to_string(), fee_bps_uref.into());
    
    let frozen_uref = storage::new_uref(false);
    named_keys.insert(KEY_FROZEN.to_string(), frozen_uref.into());
    
    let fee_purse = system::create_purse();
    named_keys.insert(KEY_FEE_PURSE.to_string(), fee_purse.into());
    
    let escrow_dict = storage::new_dictionary(KEY_ESCROWS).unwrap_or_revert();
    named_keys.insert(KEY_ESCROW_DICT.to_string(), escrow_dict.into());
    
    let entry_points = get_entry_points();
    
    let (contract_hash, _version) = storage::new_contract(entry_points, Some(named_keys), None, None, None);
    
    runtime::put_key("escrow_manager", contract_hash.into());
}