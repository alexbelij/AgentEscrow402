// Property-based tests for escrow-manager's on-chain choreography linkage
// (`link_escrows` / `get_link`).
//
// Rationale — same as the sibling property_tests / fsm_property_tests files:
// the contract crate is `#![no_std] #![no_main]` and only buildable for
// wasm32, so the input validator and append-only storage semantics of
// `link_escrows` are re-expressed here as a pure `std` model that mirrors
// the on-chain guards line-for-line. If this model drifts from
// contracts/escrow-manager/src/main.rs, the drift *is* the finding —
// every predicate here carries a line-anchored comment pointing back to
// the contract.
//
// Coverage (see P0.1.5 in KNOWN_LIMITATIONS.md — this file closes that
// gap for the pure-input + append-only pieces; the real-WASM VM
// regression is a separate future artifact, tracked as P0.1.6):
//
//   1. `is_64_lower_hex` — strict-lowercase 64-char hex validator, the
//      single canonicalization point on the boundary (main.rs:113–130).
//   2. `link_dict_key` — deterministic `"{parent}|{child}"` composition,
//      byte-for-byte reproducible off-chain (main.rs:104–115).
//   3. Append-only invariant — once (parent, child) is written, a second
//      link_escrows() for the same key MUST revert; the record after any
//      valid+attempted-duplicate sequence is exactly the FIRST accepted
//      record (main.rs:475–486).
//   4. hop_index handling — recorded verbatim, not overwritten across
//      distinct (parent, child) pairs; the contract does not enforce
//      strict monotonicity between DIFFERENT pairs (that constraint is a
//      backend/IntentChain concern, not on-chain), but WITHIN the same
//      (parent, child) key the first-write value wins.
//   5. Self-link rejection — parent == child MUST revert
//      (main.rs:466–469).
//
// Nothing here touches Casper types, storage, or crypto — these are pure
// model-checking properties on the boundary-visible behavior.

use proptest::prelude::*;

// ── Mirrored contract helpers ──────────────────────────────────────────

/// Mirror of `is_64_lower_hex` in
/// contracts/escrow-manager/src/main.rs:117–130. Line-for-line.
fn is_64_lower_hex(s: &str) -> bool {
    if s.len() != 64 {
        return false;
    }
    for c in s.chars() {
        match c {
            '0'..='9' | 'a'..='f' => {}
            _ => return false,
        }
    }
    true
}

/// Mirror of `link_dict_key` in
/// contracts/escrow-manager/src/main.rs:104–115. Line-for-line.
fn link_dict_key(parent: &str, child: &str) -> String {
    let mut key = String::with_capacity(parent.len() + 1 + child.len());
    key.push_str(parent);
    key.push('|');
    key.push_str(child);
    key
}

// ── link_escrows state-model (append-only dictionary) ──────────────────

/// Per-record shape mirrors the contract's dictionary value:
///   (chain_root_hash, hop_index, (linked_at, linker)).
/// `linked_at` / `linker` are runtime-injected on-chain (`get_blocktime` /
/// `get_caller`), so the model treats them as opaque tokens — the
/// invariants we check don't depend on their content, only on write-once
/// semantics.
#[derive(Debug, Clone, PartialEq, Eq)]
struct LinkRecord {
    chain_root_hash: String,
    hop_index: u64,
    linked_at: u64,
    linker: String,
}

/// User-supplied error codes we surface to callers. Mirrors the
/// ERROR_LINK_* constants in contracts/escrow-manager/src/constants.rs.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum LinkError {
    InvalidHash,
    AlreadyExists,
}

/// Pure model of the contract's link_escrows entry point.
///
/// Returns `Err(_)` when the on-chain guard would revert; on `Ok(())` the
/// state has been updated. Every arm mirrors one branch of the
/// `pub extern "C" fn link_escrows` body in main.rs:448–491.
fn link_escrows(
    state: &mut std::collections::BTreeMap<String, LinkRecord>,
    parent: &str,
    child: &str,
    chain_root: &str,
    hop_index: u64,
    linked_at: u64,
    linker: &str,
) -> Result<(), LinkError> {
    // main.rs:456–462
    if !is_64_lower_hex(parent) || !is_64_lower_hex(child) || !is_64_lower_hex(chain_root) {
        return Err(LinkError::InvalidHash);
    }
    // main.rs:464–466
    if parent == child {
        return Err(LinkError::InvalidHash);
    }
    let key = link_dict_key(parent, child);
    // main.rs:475–486 — append-only guard
    if state.contains_key(&key) {
        return Err(LinkError::AlreadyExists);
    }
    state.insert(
        key,
        LinkRecord {
            chain_root_hash: chain_root.to_string(),
            hop_index,
            linked_at,
            linker: linker.to_string(),
        },
    );
    Ok(())
}

/// Pure model of get_link — Some(record) iff link_escrows previously
/// succeeded for the same (parent, child); None otherwise. main.rs:498–516.
fn get_link(
    state: &std::collections::BTreeMap<String, LinkRecord>,
    parent: &str,
    child: &str,
) -> Option<LinkRecord> {
    if !is_64_lower_hex(parent) || !is_64_lower_hex(child) {
        return None; // Contract reverts InvalidHash; we return None to match
                     // the "no record readable" observable outcome.
    }
    state.get(&link_dict_key(parent, child)).cloned()
}

// ── Strategy helpers ───────────────────────────────────────────────────

fn valid_64_lower_hex() -> impl Strategy<Value = String> {
    // Uses proptest's `String::from` codec: 64 chars from the exact set
    // the contract accepts.
    prop::string::string_regex("[0-9a-f]{64}").unwrap()
}

fn arbitrary_string_64() -> impl Strategy<Value = String> {
    // Full unicode-ish string ~64 chars — used to test the negative side of
    // is_64_lower_hex. Includes uppercase, punctuation, non-hex.
    prop::string::string_regex(".{0,80}").unwrap()
}

proptest! {
    // ── is_64_lower_hex ────────────────────────────────────────────────

    #[test]
    fn valid_lowercase_hex_always_accepted(s in valid_64_lower_hex()) {
        prop_assert!(is_64_lower_hex(&s));
    }

    #[test]
    fn uppercase_hex_rejected(s in "[0-9A-F]{64}") {
        // Contains at least one uppercase letter with high probability;
        // filter to the subset that actually does.
        prop_assume!(s.chars().any(|c| c.is_ascii_uppercase()));
        prop_assert!(!is_64_lower_hex(&s));
    }

    #[test]
    fn wrong_length_rejected(s in arbitrary_string_64()) {
        prop_assume!(s.len() != 64);
        prop_assert!(!is_64_lower_hex(&s));
    }

    #[test]
    fn non_hex_char_rejected(s in "[0-9a-f]{63}[g-zA-Z!@#\\$%^&*()_+=\\-]") {
        // The regex quantifier caps the leading run at 63 lower-hex chars
        // followed by exactly one single-byte non-hex ASCII char (uppercase,
        // lowercase g-z, punctuation), giving len == 64 with a single
        // non-hex boundary. Constrained to ASCII so byte-length equals
        // char count (the contract's is_64_lower_hex uses `.chars()` and
        // `s.len()` returns BYTES — multibyte unicode would make len != 64).
        prop_assert_eq!(s.len(), 64);
        prop_assert!(!is_64_lower_hex(&s));
    }

    #[test]
    fn multibyte_unicode_boundary_rejected(prefix in "[0-9a-f]{63}") {
        // Separate check that a multibyte char in the 64th position also
        // makes is_64_lower_hex return false — even though `s.len()` is
        // 63 + N > 64 in bytes, the contract's length check triggers on
        // byte length ≠ 64 first, and even if the byte-length happened to
        // sum to 64 the .chars() branch would reject the non-hex char.
        let s = format!("{}¡", prefix); // U+00A1 = 2 bytes
        prop_assert!(!is_64_lower_hex(&s));
    }

    // ── link_dict_key ──────────────────────────────────────────────────

    #[test]
    fn dict_key_is_deterministic_and_separator_safe(
        parent in valid_64_lower_hex(),
        child in valid_64_lower_hex(),
    ) {
        prop_assume!(parent != child);
        let k1 = link_dict_key(&parent, &child);
        let k2 = link_dict_key(&parent, &child);
        // Determinism.
        prop_assert_eq!(&k1, &k2);
        // Length is exactly 64 + 1 + 64.
        prop_assert_eq!(k1.len(), 129);
        // Separator '|' cannot appear inside a lower-hex string, so the
        // only '|' in the key is the intentional separator.
        prop_assert_eq!(k1.matches('|').count(), 1);
        // Directional — reversing halves changes the key. This matters
        // because (A, B) and (B, A) are DIFFERENT hops (parent vs child
        // asymmetry), and the contract stores them under different keys.
        let reversed = link_dict_key(&child, &parent);
        prop_assert_ne!(k1, reversed);
    }

    // ── link_escrows: input validation ─────────────────────────────────

    #[test]
    fn self_link_rejected(
        h in valid_64_lower_hex(),
        chain_root in valid_64_lower_hex(),
        hop in any::<u64>(),
    ) {
        let mut state = std::collections::BTreeMap::new();
        prop_assert_eq!(
            link_escrows(&mut state, &h, &h, &chain_root, hop, 0, "acct-hash-abc"),
            Err(LinkError::InvalidHash)
        );
        prop_assert!(state.is_empty(), "self-link must not touch state");
    }

    #[test]
    fn uppercase_input_rejected(
        parent_upper in "[0-9A-F]{64}",
        child in valid_64_lower_hex(),
        chain_root in valid_64_lower_hex(),
        hop in any::<u64>(),
    ) {
        prop_assume!(parent_upper != child);
        prop_assume!(parent_upper.chars().any(|c| c.is_ascii_uppercase()));
        let mut state = std::collections::BTreeMap::new();
        prop_assert_eq!(
            link_escrows(&mut state, &parent_upper, &child, &chain_root, hop, 0, "acct-hash-abc"),
            Err(LinkError::InvalidHash)
        );
        prop_assert!(state.is_empty());
    }

    // ── Append-only invariant ──────────────────────────────────────────

    #[test]
    fn duplicate_link_reverts_and_first_write_wins(
        parent in valid_64_lower_hex(),
        child in valid_64_lower_hex(),
        chain_root_a in valid_64_lower_hex(),
        chain_root_b in valid_64_lower_hex(),
        hop_a in any::<u64>(),
        hop_b in any::<u64>(),
        linked_at_a in any::<u64>(),
        linked_at_b in any::<u64>(),
    ) {
        prop_assume!(parent != child);
        // We want a meaningful "second-write differs" case: chain-root OR
        // hop different between the two attempts, otherwise the invariant
        // is trivial.
        prop_assume!(chain_root_a != chain_root_b || hop_a != hop_b);

        let mut state = std::collections::BTreeMap::new();

        // First write succeeds.
        prop_assert!(link_escrows(
            &mut state, &parent, &child, &chain_root_a, hop_a, linked_at_a, "acct-A",
        ).is_ok());

        // Snapshot the record after the first (accepted) write.
        let snapshot = get_link(&state, &parent, &child).expect("record must exist");
        prop_assert_eq!(snapshot.chain_root_hash.as_str(), chain_root_a.as_str());
        prop_assert_eq!(snapshot.hop_index, hop_a);

        // Second write MUST revert.
        prop_assert_eq!(
            link_escrows(
                &mut state, &parent, &child, &chain_root_b, hop_b, linked_at_b, "acct-B",
            ),
            Err(LinkError::AlreadyExists)
        );

        // Record after the attempted overwrite is IDENTICAL to the first-
        // write snapshot — no fields silently mutated.
        let after = get_link(&state, &parent, &child).expect("record must still exist");
        prop_assert_eq!(after, snapshot);
    }

    // ── Cross-pair independence ────────────────────────────────────────

    #[test]
    fn distinct_pairs_can_coexist_with_arbitrary_hop_indices(
        parent_a in valid_64_lower_hex(),
        child_a in valid_64_lower_hex(),
        parent_b in valid_64_lower_hex(),
        child_b in valid_64_lower_hex(),
        chain_root in valid_64_lower_hex(),
        hop_a in any::<u64>(),
        hop_b in any::<u64>(),
    ) {
        // Distinct hops means distinct (parent, child) tuples.
        prop_assume!(parent_a != child_a);
        prop_assume!(parent_b != child_b);
        prop_assume!((parent_a.as_str(), child_a.as_str()) != (parent_b.as_str(), child_b.as_str()));

        let mut state = std::collections::BTreeMap::new();

        prop_assert!(link_escrows(
            &mut state, &parent_a, &child_a, &chain_root, hop_a, 0, "acct",
        ).is_ok());
        prop_assert!(link_escrows(
            &mut state, &parent_b, &child_b, &chain_root, hop_b, 0, "acct",
        ).is_ok());

        // Both records readable independently.
        let a = get_link(&state, &parent_a, &child_a).expect("A must exist");
        let b = get_link(&state, &parent_b, &child_b).expect("B must exist");
        prop_assert_eq!(a.hop_index, hop_a);
        prop_assert_eq!(b.hop_index, hop_b);

        // On-chain does NOT enforce strict monotonicity across different
        // (parent, child) pairs — that's an off-chain IntentChain concern
        // (see server/intent_chain.py). Cross-pair hop-index inequality
        // is not an invariant; we assert BOTH values are exactly what was
        // written and reject any silent normalization.
        prop_assert_eq!(a.hop_index, hop_a);
        prop_assert_eq!(b.hop_index, hop_b);
    }

    // ── Directional keying ─────────────────────────────────────────────

    #[test]
    fn reversed_pair_is_a_different_link(
        parent in valid_64_lower_hex(),
        child in valid_64_lower_hex(),
        chain_root_a in valid_64_lower_hex(),
        chain_root_b in valid_64_lower_hex(),
        hop_a in any::<u64>(),
        hop_b in any::<u64>(),
    ) {
        prop_assume!(parent != child);

        let mut state = std::collections::BTreeMap::new();

        // Link (parent, child).
        prop_assert!(link_escrows(
            &mut state, &parent, &child, &chain_root_a, hop_a, 0, "acct",
        ).is_ok());

        // Link (child, parent) — reversed pair. MUST be independently
        // acceptable; the append-only guard is on the ordered pair, not
        // on the unordered set. On-chain the two keys are distinct
        // dictionary entries.
        prop_assert!(link_escrows(
            &mut state, &child, &parent, &chain_root_b, hop_b, 0, "acct",
        ).is_ok());

        // Both directions readable, each carrying its own root/hop.
        let fwd = get_link(&state, &parent, &child).expect("fwd exists");
        let rev = get_link(&state, &child, &parent).expect("rev exists");
        prop_assert_eq!(fwd.chain_root_hash, chain_root_a);
        prop_assert_eq!(rev.chain_root_hash, chain_root_b);
        prop_assert_eq!(fwd.hop_index, hop_a);
        prop_assert_eq!(rev.hop_index, hop_b);
    }
}

// ── Concrete regression tests (deterministic, not proptest) ─────────────
//
// A few hand-crafted cases that pin down specific expected behaviors so
// a regression is caught even if the proptest search space happens not
// to hit that shape on a given run.

#[test]
fn is_64_lower_hex_rejects_63_char_input() {
    let s = "a".repeat(63);
    assert!(!is_64_lower_hex(&s));
}

#[test]
fn is_64_lower_hex_rejects_65_char_input() {
    let s = "a".repeat(65);
    assert!(!is_64_lower_hex(&s));
}

#[test]
fn is_64_lower_hex_accepts_all_lower_hex_chars() {
    // "0123456789abcdef" × 4 = 64 chars, every legal char represented.
    let s = "0123456789abcdef".repeat(4);
    assert_eq!(s.len(), 64);
    assert!(is_64_lower_hex(&s));
}

#[test]
fn link_dict_key_shape() {
    let p = "a".repeat(64);
    let c = "b".repeat(64);
    let k = link_dict_key(&p, &c);
    assert_eq!(k.len(), 129);
    assert!(k.contains('|'));
    assert_eq!(k.chars().nth(64), Some('|'));
}

#[test]
fn empty_state_get_link_is_none() {
    let state = std::collections::BTreeMap::new();
    let p = "a".repeat(64);
    let c = "b".repeat(64);
    assert!(get_link(&state, &p, &c).is_none());
}

#[test]
fn get_link_with_invalid_hash_returns_none() {
    let state = std::collections::BTreeMap::new();
    let bad = "NOT_HEX".to_string();
    let ok = "a".repeat(64);
    assert!(get_link(&state, &bad, &ok).is_none());
    assert!(get_link(&state, &ok, &bad).is_none());
}
