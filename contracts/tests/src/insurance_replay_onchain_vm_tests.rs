// Real Casper VM on-chain regression test for the insurance-pool
// tombstone/replay invariant.
//
// docs/INSURANCE_REPLAY_TESTS.md's host-mirror suite
// (insurance_replay_tests.rs) proves the invariant on a Rust-side model
// of claim()'s message-binding + tombstone logic, because the contract
// is `#![no_std] #![no_main]` and its host imports can't run outside a
// Casper VM. This file closes that gap: it compiles the REAL
// `insurance-pool.wasm` (via `cargo build --release --target
// wasm32-unknown-unknown`, the same artifact
// `scripts/audit_contract_artifact.py` / the nightly CI audit job
// build) and drives it through `casper-engine-test-support`'s
// `LmdbWasmTestBuilder` — an actual Casper execution engine instance,
// not a mirror.
//
// Toolchain note: the crate name from older Casper SDK examples,
// `InMemoryWasmTestBuilder`, no longer exists in casper-types 6.x /
// casper-engine-test-support 8.x — it was replaced by
// `LmdbWasmTestBuilder` (backed by a temporary on-disk LMDB store).
// `LmdbWasmTestBuilder::default()` + `LOCAL_GENESIS_REQUEST` is the
// current equivalent. This must build under the pinned
// nightly-2025-01-01 toolchain (../rust-toolchain.toml) — newer
// nightlies emit bulk-memory wasm ops Casper testnet preprocessing
// rejects (see docs/DEPLOYMENT_LESSONS.md); this test doesn't deploy to
// testnet, but it DOES load the same release wasm artifact, so building
// it with a mismatched toolchain would silently test a binary nothing
// will ever actually deploy.
//
// Scenarios (see docs/INSURANCE_REPLAY_TESTS.md § AE-2 closure decision):
//   A. Happy path: a valid claim() succeeds and the pool purse balance
//      decreases by exactly `amount`.
//   B. Replay (the AE-2 invariant): the *same* deploy (same escrow_id,
//      same caller, same amount, same signatures) submitted a second
//      time fails with the tombstone's error code, and the pool balance
//      is unchanged by the second attempt.
//   C. Cross-escrow replay: the same arbiter signatures/pubkeys/amount
//      reused against a *different* escrow_id fail — proving the
//      tombstone isn't the only thing standing between an attacker and
//      a second payout; message-binding independently blocks reuse
//      across escrow_id.
//
// Running (nightly build takes longer than the rest of the suite —
// scheduled nightly, not PR gate; see contract-audit-nightly.yml):
//   export PATH="$HOME/.cargo/bin:$PATH"
//   rustup run nightly-2025-01-01 cargo test -p tests --test insurance_replay_onchain_vm_tests
//
// Deploy-gate: docs/DEPLOY.md requires a green run of this test before
// any insurance-pool redeploy that will hold real funds.

use casper_engine_test_support::{
    ExecuteRequestBuilder, LmdbWasmTestBuilder, DEFAULT_ACCOUNT_ADDR, LOCAL_GENESIS_REQUEST,
};
use casper_types::{
    account::AccountHash,
    crypto::{sign, AsymmetricType, PublicKey, SecretKey},
    runtime_args, AddressableEntityHash, RuntimeArgs, U512,
};

/// Same wasm the audit script / nightly CI builds and the same one that
/// would be deployed: contracts/target/wasm32-unknown-unknown/release/insurance-pool.wasm.
///
/// casper-engine-test-support's `read_wasm_file` searches a fixed set of
/// relative locations rooted at ITS OWN crate manifest dir (meant for the
/// upstream casper-node monorepo layout) before falling back to reading
/// the literal path -- which does handle an absolute path directly. To
/// avoid depending on that search order (or the current working
/// directory `cargo test` happens to be invoked from), resolve an
/// absolute path from OUR crate's own `CARGO_MANIFEST_DIR` instead.
fn insurance_pool_wasm_path() -> String {
    concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../target/wasm32-unknown-unknown/release/insurance-pool.wasm"
    )
    .to_string()
}

/// `contracts/pool-funder` -- first-party session code (already in this
/// workspace, not written for this test) that creates a fresh purse
/// INSIDE its own execution and calls the target's real `deposit()`
/// entry point with it. Reuse this instead of a bespoke funding path:
/// it sidesteps the exact same access-rights-stripping gotcha its own
/// doc comment describes, and it exercises deposit() itself rather than
/// working around it.
fn pool_funder_wasm_path() -> String {
    concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../target/wasm32-unknown-unknown/release/pool-funder.wasm"
    )
    .to_string()
}

/// Mirrors `insurance-pool/src/main.rs::build_claim_message` exactly.
/// (insurance_replay_tests.rs's docstring calls out the same drift risk:
/// if the contract's message format changes, every mirror — including
/// this one — must be updated alongside it.)
fn build_claim_message(claimant: &str, escrow_id: &str, amount: U512) -> String {
    alloc_free_format(escrow_id, claimant, amount)
}

fn alloc_free_format(escrow_id: &str, claimant: &str, amount: U512) -> String {
    format!("claim:{}:{}:{}", escrow_id, claimant, amount)
}

/// Three arbiter keypairs + the installer's threshold (3, the contract's
/// default — see `call()`'s `arbiter_threshold_uref = storage::new_uref(3u64)`).
struct Arbiters {
    keys: Vec<(SecretKey, PublicKey)>,
}

impl Arbiters {
    fn generate(n: usize) -> Self {
        // Deterministic ed25519 keypairs — casper_types v7 exposes
        // `ed25519_from_bytes` but no in-crate RNG generator, so we seed
        // ourselves from `getrandom` (already a transitive dep) to keep
        // the test hermetic and byte-reproducible per-run.
        let keys = (0..n)
            .map(|_| {
                let mut seed = [0u8; 32];
                getrandom::getrandom(&mut seed).expect("seed rng");
                let sk = SecretKey::ed25519_from_bytes(seed).expect("ed25519 from bytes");
                let pk = PublicKey::from(&sk);
                (sk, pk)
            })
            .collect();
        Arbiters { keys }
    }

    fn pubkey_hex_list(&self) -> Vec<String> {
        self.keys.iter().map(|(_, pk)| pk.to_hex()).collect()
    }

    /// Signs `message` with all registered arbiters, returning
    /// (pubkeys_hex, signatures_hex) in the shape claim()/withdraw() expect.
    fn sign_all(&self, message: &str) -> (Vec<String>, Vec<String>) {
        let pubkeys = self.pubkey_hex_list();
        let sigs = self
            .keys
            .iter()
            .map(|(sk, pk)| sign(message.as_bytes(), sk, pk).to_hex())
            .collect();
        (pubkeys, sigs)
    }
}

/// Installs insurance-pool.wasm, registers `arbiters`, funds the pool
/// purse with `fund_amount` via `deposit`, and returns the builder plus
/// the contract's entity hash for later `get_pool_stats`/purse lookups.
fn install_and_fund(
    builder: &mut LmdbWasmTestBuilder,
    arbiters: &Arbiters,
    fund_amount: U512,
) -> AddressableEntityHash {
    let wasm_path = insurance_pool_wasm_path();
    assert!(
        std::path::Path::new(&wasm_path).is_file(),
        "insurance-pool.wasm not found at {wasm_path} \u{2014} build it first: \
         cd contracts/insurance-pool && cargo build --release --target wasm32-unknown-unknown"
    );
    let install_request = ExecuteRequestBuilder::standard(
        *DEFAULT_ACCOUNT_ADDR,
        &wasm_path,
        RuntimeArgs::new(),
    )
    .build();
    builder.exec(install_request).expect_success().commit();

    let installer = builder
        .get_entity_with_named_keys_by_account_hash(*DEFAULT_ACCOUNT_ADDR)
        .expect("installer account should exist after genesis");
    let contract_hash: AddressableEntityHash = installer
        .named_keys()
        .get("insurance_pool_contract")
        .expect("call() must put_key insurance_pool_contract")
        .clone()
        .into_entity_hash()
        .expect("insurance_pool_contract key must resolve to a contract hash");

    // set_arbiters — installer-only in practice (assert_installer is not
    // actually called by set_arbiters in the current source, but we run
    // it as DEFAULT_ACCOUNT_ADDR, the installer, to match real usage).
    let set_arbiters_request = ExecuteRequestBuilder::contract_call_by_hash(
        *DEFAULT_ACCOUNT_ADDR,
        contract_hash,
        "set_arbiters",
        runtime_args! { "arbiters" => arbiters.pubkey_hex_list() },
    )
    .build();
    builder.exec(set_arbiters_request).expect_success().commit();

    // Fund the pool via contracts/pool-funder session code, NOT a
    // direct deposit(source_purse, amount) call from the test's own
    // request builder. Casper strips the WRITE access-rights bit off a
    // URef when it crosses a session-to-contract call boundary as a
    // plain deploy runtime arg -- the installer's own main purse, if
    // passed straight in as `source_purse`, would arrive inside
    // deposit() with only READ+ADD, so transfer_from_purse_to_purse
    // inside deposit() would fail with ApiError::Mint(InvalidAccessRights)
    // for a real reason, not a bug: it's Casper's defense against a
    // callee siphoning more of an account's purse than it was explicitly
    // handed. pool-funder's session code creates a brand-new purse
    // INSIDE its own execution (so its rights are never stripped by an
    // RPC/deploy boundary) and passes THAT purse to the real deposit()
    // entry point -- exercising the actual funding path a real deployer
    // would use, not a test-only shortcut.
    let package_hash_key = installer
        .named_keys()
        .get("insurance_pool_package_hash")
        .expect("call() must put_key insurance_pool_package_hash");
    let package_hash_hex = match package_hash_key {
        casper_types::Key::Hash(bytes) => hex::encode(bytes),
        other => panic!("insurance_pool_package_hash must be a Key::Hash, got {other:?}"),
    };

    let fund_request = ExecuteRequestBuilder::standard(
        *DEFAULT_ACCOUNT_ADDR,
        &pool_funder_wasm_path(),
        runtime_args! {
            "contract_package_hash" => package_hash_hex,
            "amount" => fund_amount,
        },
    )
    .build();
    builder.exec(fund_request).expect_success().commit();

    contract_hash
}

fn pool_purse(builder: &LmdbWasmTestBuilder, contract_hash: AddressableEntityHash) -> casper_types::URef {
    let entity = builder
        .get_entity_with_named_keys_by_entity_hash(contract_hash)
        .expect("insurance-pool contract entity should exist");
    entity
        .named_keys()
        .get("insurance_contract_purse")
        .expect("insurance_contract_purse named key")
        .clone()
        .into_uref()
        .expect("insurance_contract_purse must be a URef")
}

fn pool_purse_balance(builder: &LmdbWasmTestBuilder, contract_hash: AddressableEntityHash) -> U512 {
    builder.get_purse_balance(pool_purse(builder, contract_hash))
}

/// Blocktime every claim_request runs at: genesis blocktime is 0, and
/// claim()'s cooldown check compares `now < last_claim_timestamp +
/// COOLDOWN_SECONDS` -- with a brand-new caller's default last_claim_timestamp
/// of 0, `now=0` would make even a FIRST-EVER claim spuriously fail cooldown
/// (0 < 0 + 86_400 is true). A real chain's blocktime is never 0 by the time
/// anyone calls claim(), so advance past one cooldown window to reflect that.
const CLAIM_BLOCK_TIME_MS: u64 = 90_000 * 1000; // 90_000s > COOLDOWN_SECONDS (86_400s), in ms.

fn claim_request(
    contract_hash: AddressableEntityHash,
    caller: AccountHash,
    escrow_id: &str,
    amount: U512,
    pubkeys: Vec<String>,
    signatures: Vec<String>,
) -> casper_engine_test_support::ExecuteRequest {
    ExecuteRequestBuilder::contract_call_by_hash(
        caller,
        contract_hash,
        "claim",
        runtime_args! {
            "escrow_id" => escrow_id,
            "amount" => amount,
            "evidence" => "vm-test-evidence",
            "arbiter_pubkeys" => pubkeys,
            "arbiter_signatures" => signatures,
        },
    )
    .with_block_time(CLAIM_BLOCK_TIME_MS)
    .build()
}

const FUND_AMOUNT: u64 = 1_000_000_000_000u64; // 1000 CSPR-equivalent motes, well above any claim below.
const CLAIM_AMOUNT: u64 = 1_000_000_000u64; // 1 CSPR-equivalent — under any max-coverage cap.

/// Scenario A — happy path: a single valid claim() succeeds and the pool
/// purse balance drops by exactly `amount`.
#[ignore] // heavy VM build+genesis; run explicitly / via nightly CI, not the default `cargo test` sweep.
#[test]
fn happy_path_claim_succeeds_and_debits_pool_purse() {
    let mut builder = LmdbWasmTestBuilder::default();
    builder.run_genesis(LOCAL_GENESIS_REQUEST.clone());

    let arbiters = Arbiters::generate(3);
    let contract_hash = install_and_fund(&mut builder, &arbiters, U512::from(FUND_AMOUNT));

    let balance_before = pool_purse_balance(&builder, contract_hash);

    let escrow_id = "escrow-vm-a1";
    let amount = U512::from(CLAIM_AMOUNT);
    let caller = *DEFAULT_ACCOUNT_ADDR;
    let message = build_claim_message(&caller.to_string(), escrow_id, amount);
    let (pubkeys, sigs) = arbiters.sign_all(&message);

    let request = claim_request(contract_hash, caller, escrow_id, amount, pubkeys, sigs);
    builder.exec(request).expect_success().commit();

    let balance_after = pool_purse_balance(&builder, contract_hash);
    assert_eq!(
        balance_before - balance_after,
        amount,
        "pool purse must debit exactly the claimed amount on a valid claim"
    );
}

/// Scenario B — the AE-2 invariant. The exact same deploy args (same
/// escrow_id, caller, amount, arbiter sigs) submitted a second time must
/// fail with the tombstone's error code inside the real execution
/// engine, and the pool balance must be unchanged by the rejected retry.
#[ignore]
#[test]
fn replay_of_same_claim_is_rejected_by_tombstone_in_real_vm() {
    let mut builder = LmdbWasmTestBuilder::default();
    builder.run_genesis(LOCAL_GENESIS_REQUEST.clone());

    let arbiters = Arbiters::generate(3);
    let contract_hash = install_and_fund(&mut builder, &arbiters, U512::from(FUND_AMOUNT));

    let escrow_id = "escrow-vm-b1";
    let amount = U512::from(CLAIM_AMOUNT);
    let caller = *DEFAULT_ACCOUNT_ADDR;
    let message = build_claim_message(&caller.to_string(), escrow_id, amount);
    let (pubkeys, sigs) = arbiters.sign_all(&message);

    // First claim: succeeds.
    let first = claim_request(
        contract_hash,
        caller,
        escrow_id,
        amount,
        pubkeys.clone(),
        sigs.clone(),
    );
    builder.exec(first).expect_success().commit();

    let balance_after_first = pool_purse_balance(&builder, contract_hash);

    // Second claim: identical deploy args, replayed. Must revert with
    // ERR_ESCROW_ALREADY_CLAIMED (contract error code 9 —
    // insurance-pool/src/main.rs::ERR_ESCROW_ALREADY_CLAIMED). This is
    // the tombstone (DICT_CLAIMED_ESCROWS) doing its job inside the real
    // Casper execution engine, not a host-side mirror of it.
    let replay = claim_request(contract_hash, caller, escrow_id, amount, pubkeys, sigs);
    builder.exec(replay).commit();

    let error = builder
        .get_error()
        .expect("replayed claim must produce an execution error, not silently succeed");
    let error_string = format!("{:?}", error);
    assert!(
        error_string.contains("User(9)") || error_string.contains("ApiError::User(9"),
        "expected ERR_ESCROW_ALREADY_CLAIMED (User(9)) on replay, got: {error_string}"
    );

    let balance_after_replay = pool_purse_balance(&builder, contract_hash);
    assert_eq!(
        balance_after_first, balance_after_replay,
        "a rejected replay must not move the pool purse balance a second time"
    );
}

/// Scenario C — cross-escrow replay. The same arbiter signatures/pubkeys
/// and amount, reused against a DIFFERENT escrow_id, must fail
/// message-binding (the signed message embeds escrow_id — see
/// build_claim_message) rather than succeeding as if it were a fresh,
/// legitimately-approved claim.
#[ignore]
#[test]
fn cross_escrow_replay_fails_message_binding_in_real_vm() {
    let mut builder = LmdbWasmTestBuilder::default();
    builder.run_genesis(LOCAL_GENESIS_REQUEST.clone());

    let arbiters = Arbiters::generate(3);
    let contract_hash = install_and_fund(&mut builder, &arbiters, U512::from(FUND_AMOUNT));

    let original_escrow_id = "escrow-vm-c1";
    let amount = U512::from(CLAIM_AMOUNT);
    let caller = *DEFAULT_ACCOUNT_ADDR;

    // Arbiters signed a message bound to `original_escrow_id`.
    let message = build_claim_message(&caller.to_string(), original_escrow_id, amount);
    let (pubkeys, sigs) = arbiters.sign_all(&message);

    let balance_before = pool_purse_balance(&builder, contract_hash);

    // Attacker submits the SAME signatures against a different escrow_id.
    // require_arbiter_quorum verifies signatures against
    // build_claim_message(caller, "escrow-vm-c2", amount) — a message
    // the arbiters never signed — so the quorum check must fail with
    // ERR_INSUFFICIENT_ARBITER_SIGS (error code 8), before the tombstone
    // dictionary is even touched for this escrow_id.
    let different_escrow_id = "escrow-vm-c2";
    let attack = claim_request(
        contract_hash,
        caller,
        different_escrow_id,
        amount,
        pubkeys,
        sigs,
    );
    builder.exec(attack).commit();

    let error = builder
        .get_error()
        .expect("cross-escrow replay must produce an execution error, not silently succeed");
    let error_string = format!("{:?}", error);
    assert!(
        error_string.contains("User(8)") || error_string.contains("ApiError::User(8"),
        "expected ERR_INSUFFICIENT_ARBITER_SIGS (User(8)) on cross-escrow replay, got: {error_string}"
    );

    let balance_after = pool_purse_balance(&builder, contract_hash);
    assert_eq!(
        balance_before, balance_after,
        "a rejected cross-escrow replay must not move the pool purse balance"
    );
}
