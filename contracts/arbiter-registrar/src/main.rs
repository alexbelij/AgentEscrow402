#![no_std]
#![no_main]

extern crate alloc;

use alloc::string::String;
use casper_contract::contract_api::{account, runtime, system};
use casper_contract::unwrap_or_revert::UnwrapOrRevert;
use casper_types::account::AccountHash;
use casper_types::{contracts::ContractPackageHash, runtime_args, U512};

// Generic one-shot session code: pulls `stake` motes from the caller's own
// main purse (full access rights in session context) into a brand-new purse
// created in this same execution, then natively cross-contract-calls the
// vrf-arbiter contract's `register_arbiter(account, stake, source_purse)`
// entry point with that purse's URef.
//
// Mirrors contracts/pool-funder/src/main.rs -- same reason: a purse URef
// passed as a *deploy* runtime arg over RPC has its access rights stripped
// (causing a Mint permission error on any contract-side transfer attempt);
// URefs passed via a native `call_versioned_contract` from session code to
// a stored contract are NOT re-serialized over RPC, so the rights created
// here survive.
//
// Args (deploy session args):
//   contract_package_hash: String (64-hex vrf-arbiter package hash, no "hash-" prefix)
//   account: AccountHash (the arbiter account being registered -- may be the
//     caller's own account, or (custodial operator model, same as
//     create_escrow/deposit_to_insurance_pool elsewhere in this project) any
//     account the operator key is registering on behalf of)
//   stake: U512 (motes to stake, pulled from the *caller's* main purse)
#[no_mangle]
pub extern "C" fn call() {
    let package_hash_str: String = runtime::get_named_arg("contract_package_hash");
    let arbiter_account: AccountHash = runtime::get_named_arg("account");
    // NOTE: the top-level *deploy session* arg MUST be named "amount"
    // (casper-node's ARG_AMOUNT constant, see storage/src/global_state/
    // state/mod.rs upstream). The node seeds this deploy execution's
    // `remaining_spending_limit` (Mint's approved-spending budget, tracked
    // for the whole deploy, not per call-frame) from a top-level session
    // arg literally named "amount". Without it the limit defaults to 0, and
    // ANY transfer_from_purse_to_purse where the source is the current
    // context's main purse reverts with Mint error 21
    // (UnapprovedSpendingAmount) -- this bit both our own transfer below AND
    // the vrf-arbiter contract's internal transfer inside register_arbiter().
    // The inner call_versioned_contract arg is untouched and still named
    // "stake" to match register_arbiter()'s actual entry-point parameter --
    // that's a separate arg namespace, unrelated to the top-level ARG_AMOUNT
    // mechanism. (Earlier revisions of this file used "stake_amount" here
    // based on a since-disproven "reserved name" theory; root-caused via
    // casper-node source in July 2026 -- see contracts/README.)
    let stake: U512 = runtime::get_named_arg("amount");

    let package_hash = ContractPackageHash::new(hex_to_32(&package_hash_str));

    let main_purse = account::get_main_purse();
    let new_purse = system::create_purse();
    system::transfer_from_purse_to_purse(main_purse, new_purse, stake, None).unwrap_or_revert();

    let args = runtime_args! {
        "account" => arbiter_account,
        "stake" => stake,
        "source_purse" => new_purse,
    };
    let _: () = runtime::call_versioned_contract(package_hash, None, "register_arbiter", args);
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
