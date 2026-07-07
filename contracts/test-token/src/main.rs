//! Minimal CEP-18-style fungible test token, standalone, for exercising
//! MultiAssetEscrow's on-chain transfer_from() cross-contract calls against
//! a real deployed token on testnet.
//!
//! Not a full CEP-18 spec implementation (no events, no admin/minter
//! lists) -- just the entry points MultiAssetEscrow actually calls:
//! `transfer`, `approve`, `transfer_from`, `balance_of`, `allowance`,
//! plus `name`/`symbol`/`decimals`/`total_supply` for read-only info.
//! Same entry-point names/arg names as CEP-18 so it's a drop-in stand-in.
//!
//! Constants (name/symbol/decimals/total_supply) are compile-time, not
//! deploy-time args -- avoids the ExecutableDeployItem::newModuleBytes +
//! Args.fromMap incompatibility hit when deploying the official
//! casper-ecosystem/cep18 v1.2.0 release wasm against this node (see
//! skills/projects/ae402_hackathon for the writeup), and matches this
//! repo's own escrow/agent-identity-registry install pattern (zero
//! runtime args at `call()`).

#![no_std]
#![no_main]

extern crate alloc;

use alloc::string::{String, ToString};

use casper_contract::contract_api::{runtime, storage};
use casper_contract::unwrap_or_revert::UnwrapOrRevert;
use casper_types::contracts::NamedKeys;
use casper_types::{
    ApiError, CLType, CLValue, EntityEntryPoint, EntryPointAccess, EntryPointPayment,
    EntryPointType, EntryPoints, Key, Parameter, U256,
};

const TOKEN_NAME: &str = "AE402 MultiAsset Test Token";
const TOKEN_SYMBOL: &str = "AEMAT";
const TOKEN_DECIMALS: u8 = 6;
// 1,000,000.000000 AEMAT
const TOKEN_TOTAL_SUPPLY: u64 = 1_000_000_000_000;

const NAME_KEY: &str = "name";
const SYMBOL_KEY: &str = "symbol";
const DECIMALS_KEY: &str = "decimals";
const TOTAL_SUPPLY_KEY: &str = "total_supply";
const BALANCES_DICT: &str = "balances";
const ALLOWANCES_DICT: &str = "allowances";
const PACKAGE_KEY: &str = "test_token_v2_package_hash";
const CONTRACT_KEY: &str = "test_token_v2_contract";

const INSTALLER_KEY: &str = "installer";
const INITIALIZED_KEY: &str = "initialized";

const ERR_INSUFFICIENT_BALANCE: u16 = 1;
const ERR_INSUFFICIENT_ALLOWANCE: u16 = 2;
const ERR_ALREADY_INITIALIZED: u16 = 3;
const ERR_UNAUTHORIZED: u16 = 4;

fn revert(code: u16) -> ! {
    runtime::revert(ApiError::User(code))
}

fn key_to_hex(key: &Key) -> String {
    match key {
        Key::Account(a) => a.to_string(),
        Key::Hash(h) => alloc::format!("contract-{}", hex_encode(h)),
        _ => runtime::revert(ApiError::InvalidArgument),
    }
}

fn hex_encode(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push(HEX[(b >> 4) as usize] as char);
        s.push(HEX[(b & 0x0f) as usize] as char);
    }
    s
}

fn caller_key() -> Key {
    Key::Account(runtime::get_caller())
}

fn get_dict_uref(name: &str) -> casper_types::URef {
    // Casper 2.2.x: new_dictionary() is disallowed in install/session
    // context, so create lazily on first entry-point call (same pattern
    // as escrow/agent-identity-registry in this repo).
    match runtime::get_key(name) {
        Some(key) => key.into_uref().unwrap_or_revert(),
        None => storage::new_dictionary(name).unwrap_or_revert(),
    }
}

fn read_balance(dict: casper_types::URef, owner_hex: &str) -> U256 {
    storage::dictionary_get(dict, owner_hex)
        .unwrap_or_revert()
        .unwrap_or(U256::zero())
}

fn write_balance(dict: casper_types::URef, owner_hex: &str, amount: U256) {
    storage::dictionary_put(dict, owner_hex, amount);
}

fn allowance_key(owner_hex: &str, spender_hex: &str) -> String {
    alloc::format!("{}:{}", owner_hex, spender_hex)
}

fn read_allowance(dict: casper_types::URef, owner_hex: &str, spender_hex: &str) -> U256 {
    storage::dictionary_get(dict, &allowance_key(owner_hex, spender_hex))
        .unwrap_or_revert()
        .unwrap_or(U256::zero())
}

fn write_allowance(dict: casper_types::URef, owner_hex: &str, spender_hex: &str, amount: U256) {
    storage::dictionary_put(dict, &allowance_key(owner_hex, spender_hex), amount);
}

// ── Entry points ─────────────────────────────────────────────────────

#[no_mangle]
pub extern "C" fn name() {
    runtime::ret(CLValue::from_t(TOKEN_NAME.to_string()).unwrap_or_revert());
}

#[no_mangle]
pub extern "C" fn symbol() {
    runtime::ret(CLValue::from_t(TOKEN_SYMBOL.to_string()).unwrap_or_revert());
}

#[no_mangle]
pub extern "C" fn decimals() {
    runtime::ret(CLValue::from_t(TOKEN_DECIMALS).unwrap_or_revert());
}

#[no_mangle]
pub extern "C" fn total_supply() {
    runtime::ret(CLValue::from_t(U256::from(TOKEN_TOTAL_SUPPLY)).unwrap_or_revert());
}

#[no_mangle]
pub extern "C" fn balance_of() {
    let address: Key = runtime::get_named_arg("address");
    let dict = get_dict_uref(BALANCES_DICT);
    let bal = read_balance(dict, &key_to_hex(&address));
    runtime::ret(CLValue::from_t(bal).unwrap_or_revert());
}

#[no_mangle]
pub extern "C" fn allowance() {
    let owner: Key = runtime::get_named_arg("owner");
    let spender: Key = runtime::get_named_arg("spender");
    let dict = get_dict_uref(ALLOWANCES_DICT);
    let a = read_allowance(dict, &key_to_hex(&owner), &key_to_hex(&spender));
    runtime::ret(CLValue::from_t(a).unwrap_or_revert());
}

#[no_mangle]
pub extern "C" fn approve() {
    let spender: Key = runtime::get_named_arg("spender");
    let amount: U256 = runtime::get_named_arg("amount");
    let dict = get_dict_uref(ALLOWANCES_DICT);
    let owner = caller_key();
    write_allowance(dict, &key_to_hex(&owner), &key_to_hex(&spender), amount);
}

#[no_mangle]
pub extern "C" fn transfer() {
    let recipient: Key = runtime::get_named_arg("recipient");
    let amount: U256 = runtime::get_named_arg("amount");
    let dict = get_dict_uref(BALANCES_DICT);
    let sender = caller_key();
    let sender_hex = key_to_hex(&sender);
    let recipient_hex = key_to_hex(&recipient);

    let sender_bal = read_balance(dict, &sender_hex);
    if sender_bal < amount {
        revert(ERR_INSUFFICIENT_BALANCE);
    }
    let recipient_bal = read_balance(dict, &recipient_hex);
    write_balance(dict, &sender_hex, sender_bal - amount);
    write_balance(dict, &recipient_hex, recipient_bal + amount);
}

#[no_mangle]
pub extern "C" fn transfer_from() {
    let owner: Key = runtime::get_named_arg("owner");
    let recipient: Key = runtime::get_named_arg("recipient");
    let amount: U256 = runtime::get_named_arg("amount");

    let spender = caller_key();
    let owner_hex = key_to_hex(&owner);
    let spender_hex = key_to_hex(&spender);
    let recipient_hex = key_to_hex(&recipient);

    let allow_dict = get_dict_uref(ALLOWANCES_DICT);
    let current_allowance = read_allowance(allow_dict, &owner_hex, &spender_hex);
    if current_allowance < amount {
        revert(ERR_INSUFFICIENT_ALLOWANCE);
    }

    let bal_dict = get_dict_uref(BALANCES_DICT);
    let owner_bal = read_balance(bal_dict, &owner_hex);
    if owner_bal < amount {
        revert(ERR_INSUFFICIENT_BALANCE);
    }
    let recipient_bal = read_balance(bal_dict, &recipient_hex);

    write_allowance(allow_dict, &owner_hex, &spender_hex, current_allowance - amount);
    write_balance(bal_dict, &owner_hex, owner_bal - amount);
    write_balance(bal_dict, &recipient_hex, recipient_bal + amount);
}

#[no_mangle]
pub extern "C" fn init() {
    // Casper 2.2.x: new_dictionary() is disallowed in session/install
    // context (see get_dict_uref comment above) -- minting the total
    // supply must happen in a real "Called" entry-point context, so
    // install (`call()`) just deploys the contract and this is invoked
    // as a follow-up stored-contract call by the same installer.
    if runtime::get_key(INITIALIZED_KEY).is_some() {
        revert(ERR_ALREADY_INITIALIZED);
    }
    let installer_key = runtime::get_key(INSTALLER_KEY).unwrap_or_revert();
    let installer = installer_key.into_account().unwrap_or_revert();
    if runtime::get_caller() != installer {
        revert(ERR_UNAUTHORIZED);
    }

    let balances_dict = get_dict_uref(BALANCES_DICT);
    let installer_hex = key_to_hex(&Key::Account(installer));
    write_balance(balances_dict, &installer_hex, U256::from(TOKEN_TOTAL_SUPPLY));
    // Pre-create allowances dict too so the first approve() isn't the one
    // paying the dictionary-creation gas surprise.
    get_dict_uref(ALLOWANCES_DICT);

    runtime::put_key(INITIALIZED_KEY, storage::new_uref(true).into());
}

// ── Installation ─────────────────────────────────────────────────────

#[no_mangle]
pub extern "C" fn call() {
    let installer = runtime::get_caller();

    let mut named_keys = NamedKeys::new();
    named_keys.insert(NAME_KEY.into(), storage::new_uref(TOKEN_NAME.to_string()).into());
    named_keys.insert(SYMBOL_KEY.into(), storage::new_uref(TOKEN_SYMBOL.to_string()).into());
    named_keys.insert(DECIMALS_KEY.into(), storage::new_uref(TOKEN_DECIMALS).into());
    named_keys.insert(
        TOTAL_SUPPLY_KEY.into(),
        storage::new_uref(U256::from(TOKEN_TOTAL_SUPPLY)).into(),
    );
    named_keys.insert(INSTALLER_KEY.into(), Key::Account(installer));

    let mut entry_points = EntryPoints::new();
    entry_points.add_entry_point(EntityEntryPoint::new(
        "init",
        alloc::vec![],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "name",
        alloc::vec![],
        CLType::String,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "symbol",
        alloc::vec![],
        CLType::String,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "decimals",
        alloc::vec![],
        CLType::U8,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "total_supply",
        alloc::vec![],
        CLType::U256,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "balance_of",
        alloc::vec![Parameter::new("address", CLType::Key)],
        CLType::U256,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "allowance",
        alloc::vec![
            Parameter::new("owner", CLType::Key),
            Parameter::new("spender", CLType::Key),
        ],
        CLType::U256,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "approve",
        alloc::vec![
            Parameter::new("spender", CLType::Key),
            Parameter::new("amount", CLType::U256),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "transfer",
        alloc::vec![
            Parameter::new("recipient", CLType::Key),
            Parameter::new("amount", CLType::U256),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "transfer_from",
        alloc::vec![
            Parameter::new("owner", CLType::Key),
            Parameter::new("recipient", CLType::Key),
            Parameter::new("amount", CLType::U256),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    if let Some(existing_package_key) = runtime::get_key(PACKAGE_KEY) {
        let package_hash_addr = existing_package_key.into_hash_addr().unwrap_or_revert();
        let package_hash: casper_types::contracts::ContractPackageHash = package_hash_addr.into();
        let (contract_hash, _) = storage::add_contract_version(
            package_hash,
            entry_points,
            NamedKeys::new(),
            alloc::collections::BTreeMap::new(),
        );
        runtime::put_key(CONTRACT_KEY, contract_hash.into());
        return;
    }

    let (contract_hash, _) = storage::new_contract(
        entry_points,
        Some(named_keys),
        Some(PACKAGE_KEY.into()),
        Some("test_token_access_uref".into()),
        None,
    );
    runtime::put_key(CONTRACT_KEY, contract_hash.into());
    // Minting happens in init() (a real "Called" entry point, invoked as
    // a follow-up stored-contract call), not here -- see init()'s comment.
}
