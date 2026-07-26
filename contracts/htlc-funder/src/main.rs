#![no_std]
#![no_main]

extern crate alloc;

use alloc::string::String;
use casper_contract::contract_api::{account, runtime, system};
use casper_contract::unwrap_or_revert::UnwrapOrRevert;
use casper_types::{account::AccountHash, contracts::ContractHash, runtime_args, U512};


// Session code for casper-htlc.lock(): creates a fresh purse in this
// same session context, funds it from the caller's main_purse, and
// forwards it into the stored contract's `lock` entry point.
//
// Rationale (same as pool-funder / batch-funder): a purse URef passed
// as a *deploy* runtime arg over RPC has its access rights stripped
// ("Mint error: 4 InvalidAccessRights" on any contract-side transfer);
// a URef created here inside session code and forwarded via a native
// `call_contract` to a stored contract keeps its access rights intact.
//
// Args (deploy session args):
//   contract_hash: String (64-hex, no "hash-" prefix)
//   hashlock_hex:  String (64 hex chars, sha256)
//   timelock_ms:   u64
//   receiver:      [u8;32] (account-hash bytes)
//   amount:        U512
#[no_mangle]
pub extern "C" fn call() {
    let contract_hash_str: String = runtime::get_named_arg("contract_hash");
    let hashlock_hex: String = runtime::get_named_arg("hashlock_hex");
    let timelock_ms: u64 = runtime::get_named_arg("timelock_ms");
    let receiver_str: String = runtime::get_named_arg("receiver");
    let amount: U512 = runtime::get_named_arg("amount");

    let contract_hash = ContractHash::new(hex_to_32(&contract_hash_str));
    let receiver = AccountHash::new(hex_to_32(&receiver_str));

    let main_purse = account::get_main_purse();
    let src_purse = system::create_purse();
    system::transfer_from_purse_to_purse(main_purse, src_purse, amount, None).unwrap_or_revert();

    let args = runtime_args! {
        "hashlock_hex" => hashlock_hex,
        "timelock_ms" => timelock_ms,
        "receiver" => receiver,
        "source_purse" => src_purse,
        "amount" => amount,
    };
    let _: String = runtime::call_contract(contract_hash, "lock", args);
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
