//! Host-independent half of insurance-pool, split out purely so `cargo
//! test` can run the claim-preconditions decision logic on the host
//! target. The actual wasm contract (`src/main.rs`) includes the same
//! `logic` module and adds the Casper host-function glue (storage,
//! cross-contract calls, entry points) around it.

pub mod logic;
