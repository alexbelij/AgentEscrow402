// Guards against the "mirror" test pattern silently drifting from the real
// contracts it mirrors.
//
// integration_tests.rs, property_tests.rs, insurance_replay_tests.rs, and
// agent_identity_registry_property_tests.rs each explicitly duplicate error
// codes / status codes / limits out of the real `#![no_std]` contract crates
// (escrow, insurance-pool, agent-identity-registry) because those crates
// only build for wasm32 and can't be unit-tested directly. That duplication
// is intentional (see the header comments in each file) but has no
// compiler-enforced link back to the source of truth -- a constant can be
// bumped in the real contract and the mirrored test file will keep passing
// against its own, now-wrong, copy forever.
//
// This test re-parses `const NAME: TYPE = VALUE;` declarations out of the
// real contract source files at test time (source of truth) and asserts
// that every mirrored constant with the same name in the test files has the
// identical value. It caught a real drift on 2026-07-24: the insurance
// replay tests had `ERR_ESCROW_ALREADY_CLAIMED = 11` while the actual
// insurance-pool contract defines it as `9`.
//
// This is deliberately a dumb text-based check, not a build-time link,
// because the contract crates are no_std/wasm32-only and can't be pulled in
// as a normal host-target dependency of this test crate.

use std::collections::HashMap;
use std::fs;

fn extract_consts(src: &str) -> HashMap<String, String> {
    let mut out = HashMap::new();
    for line in src.lines() {
        let line = line.trim();
        if let Some(rest) = line.strip_prefix("const ") {
            if let Some(colon) = rest.find(':') {
                let name = rest[..colon].trim().to_string();
                if let Some(eq) = rest.find('=') {
                    if let Some(semi) = rest.rfind(';') {
                        if eq < semi {
                            let value = rest[eq + 1..semi].trim().replace('_', "");
                            out.insert(name, value);
                        }
                    }
                }
            }
        }
    }
    out
}

fn read(path: &str) -> String {
    fs::read_to_string(path).unwrap_or_else(|e| panic!("failed to read {path}: {e}"))
}

/// (test file, contract file, constant names that must match)
fn mirrored_pairs() -> Vec<(&'static str, &'static str, Vec<&'static str>)> {
    vec![
        (
            "src/insurance_replay_tests.rs",
            "../insurance-pool/src/main.rs",
            vec!["ERR_INSUFFICIENT_ARBITER_SIGS", "ERR_ESCROW_ALREADY_CLAIMED"],
        ),
        (
            "src/integration_tests.rs",
            "../escrow/src/main.rs",
            vec![
                "ERR_ESCROW_NOT_FOUND",
                "ERR_UNAUTHORIZED",
                "ERR_ALREADY_DISPUTED",
                "ERR_INVALID_SIGNATURE",
                "ERR_FEE_TOO_HIGH",
                "ERR_INVALID_STATUS",
                "ERR_TTL_OUT_OF_RANGE",
                "ERR_DUPLICATE_HASH",
                "ERR_INSUFFICIENT_SIGS",
                "ERR_ZERO_AMOUNT",
                "ERR_POOL_FROZEN",
                "ERR_ALREADY_COMMITTED",
                "ERR_NO_COMMIT",
                "ERR_INVALID_PREIMAGE",
                "ERR_ALREADY_REVEALED",
                "ERR_CAP_EXCEEDED",
                "ERR_FEE_EXCEEDS_AMOUNT",
                "STATUS_PENDING",
                "STATUS_RELEASED",
                "STATUS_REFUNDED",
                "STATUS_EXPIRED",
                "STATUS_DISPUTED",
                "STATUS_RESOLVED",
                "MIN_TTL",
                "MAX_TTL",
                "MAX_FEE_BPS",
                "DEFAULT_FEE_BPS",
            ],
        ),
        (
            "src/property_tests.rs",
            "../escrow/src/main.rs",
            vec!["MIN_TTL", "MAX_TTL", "MAX_FEE_BPS"],
        ),
        (
            "src/agent_identity_registry_property_tests.rs",
            "../agent-identity-registry/src/main.rs",
            vec!["DEREGISTER_COOLDOWN_MS", "MS_PER_WEEK", "REPUTATION_DECAY_PER_WEEK"],
        ),
    ]
}

#[test]
fn mirrored_constants_match_real_contract_source() {
    let mut failures = Vec::new();
    for (test_path, contract_path, names) in mirrored_pairs() {
        let test_consts = extract_consts(&read(test_path));
        let contract_consts = extract_consts(&read(contract_path));
        for name in names {
            let test_val = test_consts
                .get(name)
                .unwrap_or_else(|| panic!("{name} not found in {test_path} (rename in this guard too)"));
            let contract_val = contract_consts
                .get(name)
                .unwrap_or_else(|| panic!("{name} not found in {contract_path} (rename in this guard too)"));
            if test_val != contract_val {
                failures.push(format!(
                    "{name}: {test_path}={test_val} but {contract_path}={contract_val}"
                ));
            }
        }
    }
    assert!(
        failures.is_empty(),
        "mirrored test constants drifted from real contract source:\n{}",
        failures.join("\n")
    );
}
