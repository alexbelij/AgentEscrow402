//! Host-independent half of MultiAssetEscrow, split out purely so `cargo
//! test` can run the state-machine logic on the host target. The actual
//! wasm contract (`src/main.rs`) includes the same `logic` module and adds
//! the Casper host-function glue (storage, cross-contract calls, entry
//! points) around it.

extern crate alloc;

pub mod logic;
