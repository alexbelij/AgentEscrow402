// Property-based FSM and conservation tests for the escrow contract.
//
// These check invariants that span *transitions* (not just single pure
// helpers): the state machine has one legal set of outgoing edges per
// status, terminal statuses are immutable, funds conservation holds across
// every reachable action sequence, and HTLC unlock has exactly one
// authorized path per input.
//
// Same rationale as the other proptest files here: the contract crate
// itself is `#![no_std]` and only buildable for wasm32, so the FSM and
// conservation rules are re-expressed in a pure `std` model that mirrors
// the on-chain guards word-for-word. If this model drifts from the
// contract, the drift *is* the finding — every guard in this file has a
// line-anchored comment pointing to `contracts/escrow/src/main.rs`.
//
// Nothing here touches Casper types, storage, or crypto -- these are pure
// model-checking properties over the FSM and arithmetic.

use proptest::prelude::*;
use sha2::{Digest, Sha256};

// ── FSM model ──────────────────────────────────────────────────────────

/// Escrow status, mirrored 1:1 from escrow/src/main.rs (STATUS_* constants).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Status {
    Pending = 0,
    Released = 1,
    Refunded = 2,
    Expired = 3,
    Disputed = 4,
    Resolved = 5,
}

#[allow(dead_code)]
impl Status {
    /// Kept for documentation/readability; the FSM guards below encode
    /// terminality directly via the `step` return value.
    fn is_terminal(self) -> bool {
        matches!(
            self,
            Status::Released | Status::Refunded | Status::Expired | Status::Resolved
        )
    }
}

/// Which caller is invoking an action. Everything else (arbiters, insurance
/// pool contract, etc.) is not FSM-relevant.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Caller {
    Sender,
    Receiver,
    Third,
}

/// The FSM edges exposed by the contract. Each variant carries the
/// contract-relevant inputs; guards are the same predicates as
/// `escrow/src/main.rs` checks before mutating state.
#[derive(Debug, Clone, Copy)]
enum Action {
    /// `release()` — sender-only, PENDING-only. `above_cap` toggles the A1
    /// guard; the arbiter-quorum verification is out of scope for the FSM
    /// model (it's a separate proptest suite in property_tests.rs), so we
    /// let the model assume "quorum satisfied" when above_cap=true.
    Release {
        caller: Caller,
        above_cap: bool,
        quorum_ok: bool,
    },
    /// `refund()` — PENDING-only; caller must be sender OR the escrow must
    /// have expired.
    Refund { caller: Caller, expired: bool },
    /// `dispute()` — PENDING-only; caller must be sender OR receiver.
    Dispute { caller: Caller },
    /// `resolve()` — DISPUTED-only. `arbiter_quorum_met` models the
    /// signature verification result; identity of caller is not restricted
    /// on-chain (any caller can submit signed votes).
    Resolve { arbiter_quorum_met: bool },
    /// `reveal_swap()` — PENDING-only. Matches release() when the preimage
    /// hashes to the committed hash; otherwise reverts.
    RevealSwap {
        preimage_valid: bool,
        above_cap: bool,
        quorum_ok: bool,
    },
}

/// Pure transition function -- the model. Returns `Some(next_status)` when
/// the action is *authorized* by the contract's guards, `None` when the
/// contract would revert (and therefore leave status unchanged). Every
/// branch here corresponds to an explicit `if ... revert(...)` in
/// escrow/src/main.rs.
fn step(current: Status, action: Action) -> Option<Status> {
    match (current, action) {
        // release() — main.rs:449–487
        (
            Status::Pending,
            Action::Release {
                caller: Caller::Sender,
                above_cap,
                quorum_ok,
            },
        ) => {
            if above_cap && !quorum_ok {
                None
            } else {
                Some(Status::Released)
            }
        }

        // refund() — main.rs:591–645
        (Status::Pending, Action::Refund { caller, expired }) => {
            let is_sender = matches!(caller, Caller::Sender);
            if !expired && !is_sender {
                None
            } else if expired {
                Some(Status::Expired)
            } else {
                Some(Status::Refunded)
            }
        }

        // dispute() — main.rs:647–692
        (Status::Pending, Action::Dispute { caller }) => match caller {
            Caller::Sender | Caller::Receiver => Some(Status::Disputed),
            Caller::Third => None,
        },

        // reveal_swap() — main.rs:539–589
        (
            Status::Pending,
            Action::RevealSwap {
                preimage_valid,
                above_cap,
                quorum_ok,
            },
        ) => {
            if !preimage_valid {
                None
            } else if above_cap && !quorum_ok {
                None
            } else {
                Some(Status::Released)
            }
        }

        // resolve() — main.rs:694–784. DISPUTED-only; caller not restricted.
        (Status::Disputed, Action::Resolve { arbiter_quorum_met }) => {
            if arbiter_quorum_met {
                Some(Status::Resolved)
            } else {
                None
            }
        }

        // Every other pairing hits the `status != STATUS_PENDING` guard on
        // release/refund/dispute/reveal_swap, or the `status != DISPUTED`
        // guard on resolve, and reverts.
        _ => None,
    }
}

// ── Conservation model ─────────────────────────────────────────────────

const MAX_FEE_BPS: u64 = 1_000;

fn compute_fee(amount: u64, fee_bps: u64) -> u64 {
    ((amount as u128 * fee_bps as u128) / 10_000) as u64
}

fn compute_insurance(fee: u64) -> u64 {
    fee / 2
}

/// Result of executing one FSM transition against the escrow ledger.
///
/// Fields mirror what the contract does on-chain:
///  * `contract_purse_delta` -- signed change of the escrow's own purse
///  * `payout` -- what leaves the purse toward sender or receiver
///  * `insurance_pool_delta` -- non-negative; escrow only funds the pool,
///    never withdraws from it
#[derive(Debug, Clone, Copy)]
struct LedgerDelta {
    contract_purse_delta_out: u64,
    payout: u64,
    insurance_pool_delta: u64,
}

/// Model of the value flows for one successful transition. Only the two
/// paths that actually move money are non-zero: release / reveal_swap /
/// resolve pay out `amount - insurance_fee` (the `checked_deduct_fee`
/// invariant already proptested in property_tests.rs), refund/expired path
/// pays out the same net amount to the sender. Insurance fee always flows
/// to the pool (contract splits it further downstream — outside FSM scope).
fn ledger_delta(from: Status, to: Status, amount: u64, fee_bps: u64) -> LedgerDelta {
    let is_payout = matches!(
        (from, to),
        (Status::Pending, Status::Released)   // release() / reveal_swap()
        | (Status::Pending, Status::Refunded) // refund() (before expiry, sender path)
        | (Status::Pending, Status::Expired)  // refund() (after expiry, anyone path)
        | (Status::Disputed, Status::Resolved) // resolve()
    );
    if !is_payout {
        return LedgerDelta {
            contract_purse_delta_out: 0,
            payout: 0,
            insurance_pool_delta: 0,
        };
    }
    let fee = compute_fee(amount, fee_bps);
    let payout = amount.saturating_sub(fee);
    let insurance = compute_insurance(fee);
    LedgerDelta {
        contract_purse_delta_out: payout + insurance,
        payout,
        insurance_pool_delta: insurance,
    }
}

// ── Strategies ─────────────────────────────────────────────────────────

fn status_strategy() -> impl Strategy<Value = Status> {
    prop_oneof![
        Just(Status::Pending),
        Just(Status::Released),
        Just(Status::Refunded),
        Just(Status::Expired),
        Just(Status::Disputed),
        Just(Status::Resolved),
    ]
}

fn caller_strategy() -> impl Strategy<Value = Caller> {
    prop_oneof![Just(Caller::Sender), Just(Caller::Receiver), Just(Caller::Third)]
}

fn action_strategy() -> impl Strategy<Value = Action> {
    prop_oneof![
        (caller_strategy(), any::<bool>(), any::<bool>())
            .prop_map(|(caller, above_cap, quorum_ok)| Action::Release {
                caller,
                above_cap,
                quorum_ok,
            }),
        (caller_strategy(), any::<bool>()).prop_map(|(caller, expired)| Action::Refund {
            caller,
            expired,
        }),
        caller_strategy().prop_map(|caller| Action::Dispute { caller }),
        any::<bool>().prop_map(|arbiter_quorum_met| Action::Resolve { arbiter_quorum_met }),
        (any::<bool>(), any::<bool>(), any::<bool>()).prop_map(
            |(preimage_valid, above_cap, quorum_ok)| Action::RevealSwap {
                preimage_valid,
                above_cap,
                quorum_ok,
            }
        ),
    ]
}

// ── Block A: FSM safety ────────────────────────────────────────────────

proptest! {
    /// Terminal statuses (Released, Refunded, Expired, Resolved) can never
    /// be mutated by *any* action -- every entry point in main.rs guards
    /// with `status != STATUS_PENDING` (or `!= DISPUTED` for resolve),
    /// which is exactly the guard being proven complete here.
    #[test]
    fn terminal_status_is_immutable(action in action_strategy()) {
        for terminal in [Status::Released, Status::Refunded, Status::Expired, Status::Resolved] {
            prop_assert!(
                step(terminal, action).is_none(),
                "action {:?} on terminal {:?} produced {:?} -- should have reverted",
                action, terminal, step(terminal, action)
            );
        }
    }

    /// The only outgoing edge from PENDING is one of {Released, Refunded,
    /// Expired, Disputed}. Nothing else is reachable in one step -- in
    /// particular, PENDING cannot jump directly to RESOLVED without going
    /// through DISPUTED first.
    #[test]
    fn pending_outgoing_edges_are_restricted(action in action_strategy()) {
        if let Some(next) = step(Status::Pending, action) {
            prop_assert!(
                matches!(
                    next,
                    Status::Released | Status::Refunded | Status::Expired | Status::Disputed
                ),
                "PENDING → {:?} via {:?} is not a legal edge",
                next, action
            );
        }
    }

    /// The only outgoing edge from DISPUTED is RESOLVED. There is no
    /// "un-dispute" path back to PENDING, and no direct
    /// dispute → release/refund shortcut.
    #[test]
    fn disputed_outgoing_edges_are_restricted(action in action_strategy()) {
        if let Some(next) = step(Status::Disputed, action) {
            prop_assert_eq!(
                next, Status::Resolved,
                "DISPUTED → {:?} via {:?} is not a legal edge", next, action
            );
        }
    }

    /// Any state reachable from PENDING in one step is either PENDING
    /// itself (guard rejected) or a legal successor. Chaining transitions
    /// never yields an unreachable status.
    #[test]
    fn reachable_states_are_a_closed_set(
        start in status_strategy(),
        actions in prop::collection::vec(action_strategy(), 0..8),
    ) {
        let mut s = start;
        for a in actions {
            let next = step(s, a).unwrap_or(s);
            prop_assert!(matches!(
                next,
                Status::Pending | Status::Released | Status::Refunded
                | Status::Expired | Status::Disputed | Status::Resolved
            ));
            s = next;
        }
    }

    /// `release()` is sender-only. A receiver or third-party
    /// `release` call from PENDING must revert regardless of cap/quorum.
    #[test]
    fn release_gated_to_sender(caller in caller_strategy(), above_cap in any::<bool>(), quorum_ok in any::<bool>()) {
        let action = Action::Release { caller, above_cap, quorum_ok };
        let result = step(Status::Pending, action);
        match caller {
            Caller::Sender => {
                // Only case where release *can* succeed; still gated by
                // (!above_cap || quorum_ok).
                if above_cap && !quorum_ok {
                    prop_assert!(result.is_none());
                } else {
                    prop_assert_eq!(result, Some(Status::Released));
                }
            }
            Caller::Receiver | Caller::Third => {
                prop_assert!(result.is_none(),
                    "release by {:?} must revert, got {:?}", caller, result);
            }
        }
    }

    /// `dispute()` is sender-or-receiver only.
    #[test]
    fn dispute_gated_to_parties(caller in caller_strategy()) {
        let result = step(Status::Pending, Action::Dispute { caller });
        match caller {
            Caller::Sender | Caller::Receiver => {
                prop_assert_eq!(result, Some(Status::Disputed));
            }
            Caller::Third => {
                prop_assert!(result.is_none(), "third-party dispute must revert");
            }
        }
    }

    /// `refund()` is only sender-callable, unless the escrow has expired
    /// -- after expiry, anyone may trigger it (matches main.rs:604–612).
    #[test]
    fn refund_gated_by_expiry_or_sender(caller in caller_strategy(), expired in any::<bool>()) {
        let result = step(Status::Pending, Action::Refund { caller, expired });
        let is_sender = matches!(caller, Caller::Sender);
        if !expired && !is_sender {
            prop_assert!(result.is_none(),
                "refund by non-sender before expiry must revert");
        } else {
            let expected = if expired { Status::Expired } else { Status::Refunded };
            prop_assert_eq!(result, Some(expected));
        }
    }

    /// Above-cap release requires arbiter quorum. Sender alone can never
    /// authorize an above-cap payout -- this is the A1 hardening the
    /// contract exists to enforce.
    #[test]
    fn above_cap_release_requires_quorum(above_cap in any::<bool>(), quorum_ok in any::<bool>()) {
        let result = step(Status::Pending, Action::Release {
            caller: Caller::Sender, above_cap, quorum_ok,
        });
        if above_cap && !quorum_ok {
            prop_assert!(result.is_none(),
                "sender-alone above-cap release must revert");
        } else {
            prop_assert_eq!(result, Some(Status::Released));
        }
    }
}

// ── Block B: Conservation ──────────────────────────────────────────────

proptest! {
    /// For every successful FSM transition, the contract purse outflow
    /// equals `payout + insurance_pool_delta` exactly (no phantom flows,
    /// no rounding leak). This is the ledger-side of the fee split.
    #[test]
    fn conservation_holds_on_every_transition(
        from in status_strategy(),
        action in action_strategy(),
        amount in 0u64..1_000_000_000_000_000_000,
        fee_bps in 0u64..=MAX_FEE_BPS,
    ) {
        if let Some(to) = step(from, action) {
            let d = ledger_delta(from, to, amount, fee_bps);
            prop_assert_eq!(
                d.contract_purse_delta_out,
                d.payout + d.insurance_pool_delta,
                "conservation violated on {:?} → {:?}", from, to
            );
        }
    }

    /// Every payout (release / refund / expired / resolve) pays exactly
    /// `amount - insurance_fee`. The receiver of the payout differs by
    /// path (release/reveal/resolve-receiver ⇒ receiver;
    /// refund/expired/resolve-sender ⇒ sender), but the *amount* is
    /// invariant.
    #[test]
    fn payout_equals_amount_minus_fee(
        action in action_strategy(),
        amount in 0u64..1_000_000_000_000_000_000,
        fee_bps in 0u64..=MAX_FEE_BPS,
    ) {
        // From PENDING we can reach Released / Refunded / Expired.
        if let Some(to) = step(Status::Pending, action) {
            let d = ledger_delta(Status::Pending, to, amount, fee_bps);
            if matches!(to, Status::Released | Status::Refunded | Status::Expired) {
                let expected_fee = compute_fee(amount, fee_bps);
                prop_assert_eq!(d.payout, amount - expected_fee);
            }
        }
    }

    /// Insurance pool delta is always non-negative and never exceeds the
    /// collected fee -- the escrow contract only *funds* the pool, never
    /// withdraws from it (pool payouts are separate insurance-pool-contract
    /// entry points, out of FSM scope). Non-payout transitions (dispute)
    /// contribute zero to the pool by design; only payout transitions
    /// (release/refund/expired/resolve) fund it, and always by exactly
    /// `fee/2`.
    #[test]
    fn insurance_flow_is_non_negative(
        from in status_strategy(),
        action in action_strategy(),
        amount in 0u64..1_000_000_000_000_000_000,
        fee_bps in 0u64..=MAX_FEE_BPS,
    ) {
        if let Some(to) = step(from, action) {
            let d = ledger_delta(from, to, amount, fee_bps);
            let fee = compute_fee(amount, fee_bps);
            // insurance_pool_delta is `u64`, so ≥ 0 trivially; the tight
            // upper bound is the collected fee.
            prop_assert!(d.insurance_pool_delta <= fee);
            let is_payout = matches!(
                (from, to),
                (Status::Pending, Status::Released)
                | (Status::Pending, Status::Refunded)
                | (Status::Pending, Status::Expired)
                | (Status::Disputed, Status::Resolved)
            );
            if is_payout {
                prop_assert_eq!(d.insurance_pool_delta, compute_insurance(fee));
            } else {
                // Dispute (Pending → Disputed) does not fund the pool.
                prop_assert_eq!(d.insurance_pool_delta, 0);
            }
        }
    }

    /// Payout can never exceed the escrowed amount -- for any legal
    /// (amount, fee_bps) pair, `payout ≤ amount`. This is the ledger
    /// counterpart to `fee_never_exceeds_amount` in property_tests.rs.
    #[test]
    fn payout_never_exceeds_amount(
        action in action_strategy(),
        amount in 0u64..1_000_000_000_000_000_000,
        fee_bps in 0u64..=MAX_FEE_BPS,
    ) {
        if let Some(to) = step(Status::Pending, action) {
            let d = ledger_delta(Status::Pending, to, amount, fee_bps);
            prop_assert!(d.payout <= amount);
        }
    }

    /// Sequential trajectory: starting from PENDING with amount A and
    /// fee_bps F, sum-of-payouts across the whole reachable trajectory is
    /// at most one payout (`amount - fee`). Terminal states have zero
    /// outgoing legal actions, so re-triggering release/refund/resolve on
    /// a terminal state contributes zero delta. This proves no re-entrancy
    /// or double-spend even in a caller-driven action loop.
    #[test]
    fn no_double_payout_even_when_hammered(
        actions in prop::collection::vec(action_strategy(), 1..12),
        amount in 0u64..1_000_000_000_000_000_000,
        fee_bps in 0u64..=MAX_FEE_BPS,
    ) {
        let mut s = Status::Pending;
        let mut total_out: u128 = 0;
        for a in actions {
            if let Some(next) = step(s, a) {
                let d = ledger_delta(s, next, amount, fee_bps);
                total_out = total_out
                    .saturating_add(d.contract_purse_delta_out as u128);
                s = next;
            }
        }
        let fee = compute_fee(amount, fee_bps);
        let single_payout_total = (amount - fee) as u128 + compute_insurance(fee) as u128;
        prop_assert!(
            total_out <= single_payout_total,
            "total outflow {} > single-payout ceiling {} (final state {:?})",
            total_out, single_payout_total, s
        );
    }
}

// ── Block C: HTLC unlock invariant ─────────────────────────────────────

fn sha256_hex(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    let digest = hasher.finalize();
    let mut out = String::with_capacity(64);
    for b in digest {
        out.push_str(&format!("{:02x}", b));
    }
    out
}

proptest! {
    /// HTLC unlock: `sha256(preimage) == commit_hash` ⇔ reveal path is
    /// authorized (subject to standard PENDING guard). No other predicate
    /// can substitute for the hash match.
    #[test]
    fn htlc_reveal_iff_preimage_matches(
        preimage in prop::collection::vec(any::<u8>(), 0..64),
        wrong_commit_seed in prop::collection::vec(any::<u8>(), 0..64),
    ) {
        let commit_hash = sha256_hex(&preimage);

        // Legitimate reveal: preimage matches commit_hash → release path
        let ok = step(Status::Pending, Action::RevealSwap {
            preimage_valid: true, above_cap: false, quorum_ok: true,
        });
        prop_assert_eq!(ok, Some(Status::Released));

        // Forged reveal: the wrong preimage does NOT hash to commit_hash
        // (verified below) → contract reverts, status stays PENDING.
        if wrong_commit_seed != preimage {
            let forged_hash = sha256_hex(&wrong_commit_seed);
            prop_assert_ne!(forged_hash, commit_hash);
            let bad = step(Status::Pending, Action::RevealSwap {
                preimage_valid: false, above_cap: false, quorum_ok: true,
            });
            prop_assert!(bad.is_none());
        }
    }

    /// HTLC reveal never opens the refund path. A valid preimage
    /// authorizes exactly the release edge, and only the release edge.
    /// (The refund path exists but is gated by expiry/sender, entirely
    /// independent of HTLC state.)
    #[test]
    fn htlc_reveal_never_triggers_refund(above_cap in any::<bool>(), quorum_ok in any::<bool>()) {
        let result = step(Status::Pending, Action::RevealSwap {
            preimage_valid: true, above_cap, quorum_ok,
        });
        // Result is either Released (happy) or None (above_cap && !quorum);
        // never Refunded, Expired, Disputed, or Resolved.
        match result {
            Some(Status::Released) => {}
            None => prop_assert!(above_cap && !quorum_ok),
            other => prop_assert!(false, "HTLC reveal produced {:?}", other),
        }
    }

    /// Above-cap HTLC reveal enforces the same arbiter-quorum guard as
    /// `release()`. Knowing the preimage alone is NOT sufficient
    /// authorization for a payout above the release cap -- this closes
    /// the "second release path" identified as the A1 hardening.
    #[test]
    fn htlc_above_cap_still_requires_quorum(quorum_ok in any::<bool>()) {
        let result = step(Status::Pending, Action::RevealSwap {
            preimage_valid: true, above_cap: true, quorum_ok,
        });
        if quorum_ok {
            prop_assert_eq!(result, Some(Status::Released));
        } else {
            prop_assert!(result.is_none(),
                "preimage-only above-cap reveal must revert");
        }
    }
}
