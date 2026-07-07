#![no_std]
#![no_main]

extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;
use casper_contract::contract_api::{account, runtime, system};
use casper_contract::unwrap_or_revert::UnwrapOrRevert;
use casper_types::{contracts::ContractPackageHash, RuntimeArgs, U512};

// Generic one-shot session code for agent-identity-registry's stake-taking
// entry points (`register_agent`, `add_stake`). Same rationale as
// pool-funder/src/main.rs: a purse URef passed as a *deploy* runtime arg
// over RPC loses its access rights ("Mint error: 4" on transfer), but a
// URef created and passed via a native `call_versioned_contract` from
// session code survives with full rights intact.
//
// Args (deploy session args):
//   contract_package_hash: String (64-hex package hash, no "hash-" prefix)
//   entry_point: String ("register_agent" or "add_stake")
//   amount: U512 (motes to stake)
//   capabilities: List<String> (ignored/ok-to-be-empty for add_stake)
#[no_mangle]
pub extern "C" fn call() {
    let package_hash_str: String = runtime::get_named_arg("contract_package_hash");
    let entry_point: String = runtime::get_named_arg("entry_point");
    let amount: U512 = runtime::get_named_arg("amount");
    let capabilities: Vec<String> = runtime::get_named_arg("capabilities");

    let package_hash = ContractPackageHash::new(hex_to_32(&package_hash_str));

    let main_purse = account::get_main_purse();
    let new_purse = system::create_purse();
    system::transfer_from_purse_to_purse(main_purse, new_purse, amount, None).unwrap_or_revert();

    let mut args = RuntimeArgs::new();
    args.insert("amount", amount).unwrap_or_revert();
    args.insert("source_purse", new_purse).unwrap_or_revert();
    if entry_point == "register_agent" {
        args.insert("capabilities", capabilities).unwrap_or_revert();
    }

    let _: () = runtime::call_versioned_contract(package_hash, None, &entry_point, args);
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
