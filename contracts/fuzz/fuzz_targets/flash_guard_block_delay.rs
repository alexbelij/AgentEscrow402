#![no_main]
//! C12 fuzz target: `flash_guard::check_block_delay` — same shape as the
//! hold-period target but for block-height. Guards against any u64 overflow
//! or off-by-one at the MIN_BLOCK_DELAY boundary.

use libfuzzer_sys::fuzz_target;
use ae402_stubs::flash_guard;

fuzz_target!(|data: (u64, u64)| {
    let (funded_block, current_block) = data;
    let blocks = current_block.saturating_sub(funded_block);
    let expected_ok = blocks >= flash_guard::MIN_BLOCK_DELAY;
    match flash_guard::check_block_delay(funded_block, current_block) {
        Ok(()) => assert!(expected_ok, "unexpected Ok for blocks={blocks}"),
        Err(_) => assert!(!expected_ok, "unexpected Err for blocks={blocks}"),
    }
});
