#![no_std]
#![no_main]

extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;
use casper_contract::contract_api::{account, runtime, system};
use casper_contract::unwrap_or_revert::UnwrapOrRevert;
use casper_types::{contracts::ContractHash, runtime_args, U512};

// Session code for escrow-manager.create_batch(): sums the requested per-escrow
// amounts, pulls that total (with full access rights, since it's the caller's
// own main purse in their own session context) into a brand-new purse created
// in this same execution, then natively cross-contract-calls the manager
// contract's create_batch(...) entry point passing that purse's URef as
// source_purse.
//
// Same rationale as contracts/pool-funder/src/main.rs: a purse URef passed as
// a *deploy* runtime arg over RPC has its access rights stripped ("Mint
// error: 4" on any contract-side transfer attempt); a URef created here and
// forwarded via a native `call_contract` from session code to a stored
// contract keeps its access rights intact.
//
// Args (deploy session args):
//   manager_contract_hash: String (64-hex contract hash, no "hash-" prefix)
//   receivers: Vec<String>       (account-hash hex strings)
//   amounts: Vec<U512>           (motes per escrow)
//   service_hashes: Vec<String>  (unique per-escrow identifiers)
//   ttls: Vec<u64>               (seconds per escrow)
#[no_mangle]
pub extern "C" fn call() {
    let contract_hash_str: String = runtime::get_named_arg("manager_contract_hash");
    let receivers: Vec<String> = runtime::get_named_arg("receivers");
    let amounts: Vec<U512> = runtime::get_named_arg("amounts");
    let service_hashes: Vec<String> = runtime::get_named_arg("service_hashes");
    let ttls: Vec<u64> = runtime::get_named_arg("ttls");

    let count = receivers.len() as u32;

    let mut total = U512::zero();
    for a in amounts.iter() {
        total += *a;
    }

    let contract_hash = ContractHash::new(hex_to_32(&contract_hash_str));

    let main_purse = account::get_main_purse();
    let new_purse = system::create_purse();
    system::transfer_from_purse_to_purse(main_purse, new_purse, total, None).unwrap_or_revert();

    let args = runtime_args! {
        "count" => count,
        "receivers" => receivers,
        "amounts" => amounts,
        "service_hashes" => service_hashes,
        "ttls" => ttls,
        "source_purse" => new_purse,
    };
    let _: Vec<String> = runtime::call_contract(contract_hash, "create_batch", args);
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
