#![no_std]
#![no_main]

extern crate alloc;

use alloc::string::String;
use casper_contract::contract_api::{account, runtime, system};
use casper_contract::unwrap_or_revert::UnwrapOrRevert;
use casper_types::{contracts::ContractPackageHash, runtime_args, U512};

// Generic one-shot session code: pulls `amount` motes from the caller's own
// main purse (full access rights, since it's the caller's own purse in their
// own session context) into a brand-new purse created in this same
// execution, then natively cross-contract-calls the target contract's
// `deposit(source_purse, amount)` entry point with that purse's URef.
//
// This sidesteps the well-known Casper gotcha where a purse URef passed as a
// *deploy* runtime arg over RPC has its access rights stripped (causing
// "Mint error: 4" on any contract-side transfer attempt): URefs passed via
// a native `call_contract` from session code to a stored contract are NOT
// re-serialized over RPC, so the rights created here survive.
//
// Args (deploy session args):
//   contract_package_hash: String (64-hex package hash, no "hash-" prefix)
//   amount: U512 (motes to deposit)
#[no_mangle]
pub extern "C" fn call() {
    let package_hash_str: String = runtime::get_named_arg("contract_package_hash");
    let amount: U512 = runtime::get_named_arg("amount");

    let package_hash = ContractPackageHash::new(hex_to_32(&package_hash_str));

    let main_purse = account::get_main_purse();
    let new_purse = system::create_purse();
    system::transfer_from_purse_to_purse(main_purse, new_purse, amount, None).unwrap_or_revert();

    let args = runtime_args! {
        "source_purse" => new_purse,
        "amount" => amount,
    };
    let _: () = runtime::call_versioned_contract(package_hash, None, "deposit", args);
}

fn hex_to_32(s: &str) -> [u8; 32] {
    let mut out = [0u8; 32];
    let bytes = s.as_bytes();
    for i in 0..32 {
        let hi = hex_val(bytes[i * 2]);
        let lo = hex_val(bytes[i * 2 + 1]);
        out[i] = (hi << 4) | lo;
    }
    out
}

fn hex_val(c: u8) -> u8 {
    match c {
        b'0'..=b'9' => c - b'0',
        b'a'..=b'f' => c - b'a' + 10,
        b'A'..=b'F' => c - b'A' + 10,
        _ => 0,
    }
}
