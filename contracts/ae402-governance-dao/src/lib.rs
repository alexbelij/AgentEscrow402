//! AE402 Governance DAO — pure logic library.
//!
//! Provenance: proposal-lifecycle primitives (proposal record shape, status
//! machine, quorum math, delegation-aware voting power, 7-day voting window,
//! veto flow) are ported from `rwa-s/contracts/governance-dao/src/main.rs`
//! (Apache-2.0). The action layer is AE402-specific and net-new — no reuse.
//! See `PROVENANCE.md` for full attribution and diff summary.
//!
//! This crate is `#![no_std]` so the WASM binary can consume it. The pure
//! logic (status transitions, quorum math, action param parsing) is also
//! covered by std proptests under `contracts/tests/src/governance_dao_property_tests.rs`.

#![no_std]

extern crate alloc;

use alloc::string::{String, ToString};
use alloc::vec::Vec;

// ────────────────────────────────────────────────────────────────────────────
// Status codes — proposal state machine
// ────────────────────────────────────────────────────────────────────────────

pub const STATUS_ACTIVE: u64 = 0;
pub const STATUS_PASSED: u64 = 1;
pub const STATUS_REJECTED: u64 = 2;
pub const STATUS_EXECUTED: u64 = 3;
pub const STATUS_VETOED: u64 = 4;
pub const STATUS_EXPIRED: u64 = 5;

// ────────────────────────────────────────────────────────────────────────────
// Action codes — AE402-specific governance surface
// ────────────────────────────────────────────────────────────────────────────

pub const ACTION_ADJUST_FEE_BPS: u64 = 0;
pub const ACTION_ROTATE_ARBITER_SET: u64 = 1;
pub const ACTION_UPDATE_INSURANCE_POOL_PARAMS: u64 = 2;
pub const ACTION_UPDATE_TIMELOCK_DELAY: u64 = 3;
pub const ACTION_UPDATE_RANGE_PROOF_PARAMS: u64 = 4;
pub const ACTION_PAUSE_PROTOCOL: u64 = 5;

pub const MAX_ACTION: u64 = ACTION_PAUSE_PROTOCOL;

// ────────────────────────────────────────────────────────────────────────────
// Governance constants
// ────────────────────────────────────────────────────────────────────────────

pub const QUORUM_PERCENT: u64 = 30;
pub const VOTING_PERIOD_SECONDS: u64 = 7 * 24 * 60 * 60;

/// Domain-separator string for the execution attestation hash. Used by
/// off-chain arbiters and by the on-chain execute pathway to bind an
/// attestation to a specific (proposal_id, action, params_hash) tuple.
pub const EXECUTION_DOMAIN: &str = "ae402:governance-dao:exec:v1";

// ────────────────────────────────────────────────────────────────────────────
// Error codes
// ────────────────────────────────────────────────────────────────────────────

pub const ERR_INVALID_ACTION: u16 = 1;
pub const ERR_INVALID_PARAMS: u16 = 2;
pub const ERR_INVALID_VOTE: u16 = 3;
pub const ERR_INVALID_STATUS_TRANSITION: u16 = 4;
pub const ERR_QUORUM_NOT_MET: u16 = 5;

// ────────────────────────────────────────────────────────────────────────────
// Vote / status math
// ────────────────────────────────────────────────────────────────────────────

/// Compute the quorum threshold in vote-weight units.
///
/// Deliberately uses u128 intermediate to avoid overflow on large stakes.
#[inline]
pub fn quorum_threshold(total_staked: u64, quorum_percent: u64) -> u64 {
    let numer = (total_staked as u128) * (quorum_percent as u128);
    (numer / 100) as u64
}

/// Compute the "effective" voting weight the voter can spend on a proposal.
///
/// Delegation semantics (ported from RWA-S): a delegator's voting power is
/// zero — they gave it away. Non-delegators can vote up to their stake.
#[inline]
pub fn effective_weight(requested: u64, voting_power: u64) -> u64 {
    if requested < voting_power {
        requested
    } else {
        voting_power
    }
}

/// Determine the proposal's status after a vote is cast (or after the voting
/// window closes). Pure function; the WASM entry point calls this and writes
/// the returned status back to storage.
///
/// Semantics:
///   * If the voting window closed AND quorum met → PASSED if for > against, else REJECTED.
///   * If the voting window closed AND quorum NOT met → EXPIRED.
///   * Otherwise (window still open): if quorum was reached during this vote,
///     we finalize (PASSED if for > against, else REJECTED). Else ACTIVE.
///
/// This matches RWA-S semantics but is factored into a pure function so
/// property tests can exhaustively enumerate the transition table.
pub fn resolve_status(
    votes_for: u64,
    votes_against: u64,
    total_staked: u64,
    quorum_percent: u64,
    current_time: u64,
    voting_end: u64,
) -> u64 {
    let threshold = quorum_threshold(total_staked, quorum_percent);
    let quorum_met = votes_for.saturating_add(votes_against) >= threshold;
    let window_closed = current_time > voting_end;

    if window_closed {
        if quorum_met {
            if votes_for > votes_against {
                STATUS_PASSED
            } else {
                STATUS_REJECTED
            }
        } else {
            STATUS_EXPIRED
        }
    } else if quorum_met {
        // Early finalization — same as RWA-S: quorum sealed while window is
        // still open triggers immediate finalization.
        if votes_for > votes_against {
            STATUS_PASSED
        } else {
            STATUS_REJECTED
        }
    } else {
        STATUS_ACTIVE
    }
}

/// Validate an action code. Constant-time boolean; used at proposal creation
/// to reject nonsensical actions before storing.
#[inline]
pub fn is_valid_action(action_type: u64) -> bool {
    action_type <= MAX_ACTION
}

// ────────────────────────────────────────────────────────────────────────────
// Params parsing — AE402 governance surface
// ────────────────────────────────────────────────────────────────────────────
//
// Params are encoded as a `key=value;key=value` string. Chosen over JSON to
// keep the no_std parser trivial (no serde) and to keep the on-chain gas
// cost bounded. The parser is exhaustive and rejects malformed input.
//
// Per-action schemas (documented in docs/GOVERNANCE.md):
//   ADJUST_FEE_BPS           bps=<u64>                          (0..=10000)
//   ROTATE_ARBITER_SET       op=<add|remove|threshold>;value=<...>
//   UPDATE_INSURANCE_POOL    max_coverage_bps=<u64>;cooldown_sec=<u64>
//   UPDATE_TIMELOCK_DELAY    delay_sec=<u64>                    (>= 3600)
//   UPDATE_RANGE_PROOF       min_bits=<u64>;max_bits=<u64>      (1..=32)
//   PAUSE_PROTOCOL           mode=<pause|unpause>

/// Parsed params for the six AE402 actions. Each variant carries only the
/// fields it actually needs — this is what the on-chain execute pathway
/// consumes when dispatching to the target contract.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ActionParams {
    AdjustFeeBps { bps: u64 },
    RotateArbiterSet { op: String, value: String },
    UpdateInsurancePool { max_coverage_bps: u64, cooldown_sec: u64 },
    UpdateTimelockDelay { delay_sec: u64 },
    UpdateRangeProof { min_bits: u64, max_bits: u64 },
    PauseProtocol { pause: bool },
}

/// Split a `key=value;key=value` string into a Vec of `(key, value)` pairs.
/// Whitespace is NOT trimmed — inputs are assumed to be produced by the
/// SDK (which enforces exact bytes). Empty segments are rejected.
///
/// Public for property tests.
pub fn split_kv(s: &str) -> Result<Vec<(String, String)>, u16> {
    let mut out: Vec<(String, String)> = Vec::new();
    if s.is_empty() {
        return Ok(out);
    }
    for segment in s.split(';') {
        if segment.is_empty() {
            return Err(ERR_INVALID_PARAMS);
        }
        let mut it = segment.splitn(2, '=');
        let k = it.next().ok_or(ERR_INVALID_PARAMS)?;
        let v = it.next().ok_or(ERR_INVALID_PARAMS)?;
        if k.is_empty() || v.is_empty() {
            return Err(ERR_INVALID_PARAMS);
        }
        out.push((k.to_string(), v.to_string()));
    }
    Ok(out)
}

/// Parse a decimal u64 without allocating (no_std-friendly). Returns
/// `Err(ERR_INVALID_PARAMS)` for empty strings, non-digit chars, or overflow.
pub fn parse_u64(s: &str) -> Result<u64, u16> {
    if s.is_empty() {
        return Err(ERR_INVALID_PARAMS);
    }
    let mut acc: u64 = 0;
    for b in s.bytes() {
        if !(b'0'..=b'9').contains(&b) {
            return Err(ERR_INVALID_PARAMS);
        }
        acc = acc
            .checked_mul(10)
            .ok_or(ERR_INVALID_PARAMS)?
            .checked_add((b - b'0') as u64)
            .ok_or(ERR_INVALID_PARAMS)?;
    }
    Ok(acc)
}

fn find_kv<'a>(pairs: &'a [(String, String)], key: &str) -> Result<&'a str, u16> {
    for (k, v) in pairs {
        if k == key {
            return Ok(v.as_str());
        }
    }
    Err(ERR_INVALID_PARAMS)
}

/// Parse action-specific params according to the schema above.
pub fn parse_params(action_type: u64, params: &str) -> Result<ActionParams, u16> {
    let pairs = split_kv(params)?;

    match action_type {
        ACTION_ADJUST_FEE_BPS => {
            let bps = parse_u64(find_kv(&pairs, "bps")?)?;
            if bps > 10_000 {
                return Err(ERR_INVALID_PARAMS);
            }
            Ok(ActionParams::AdjustFeeBps { bps })
        }
        ACTION_ROTATE_ARBITER_SET => {
            let op = find_kv(&pairs, "op")?.to_string();
            let value = find_kv(&pairs, "value")?.to_string();
            if op != "add" && op != "remove" && op != "threshold" {
                return Err(ERR_INVALID_PARAMS);
            }
            if op == "threshold" {
                // For threshold, value must be a small u64 (1..=64).
                let t = parse_u64(&value)?;
                if t == 0 || t > 64 {
                    return Err(ERR_INVALID_PARAMS);
                }
            } else {
                // For add/remove, value is expected to be a hex-encoded
                // 33-byte public key (66 hex chars). Length check only —
                // full validation happens on the target contract.
                if value.len() != 66 {
                    return Err(ERR_INVALID_PARAMS);
                }
                for b in value.bytes() {
                    let ok = (b'0'..=b'9').contains(&b)
                        || (b'a'..=b'f').contains(&b)
                        || (b'A'..=b'F').contains(&b);
                    if !ok {
                        return Err(ERR_INVALID_PARAMS);
                    }
                }
            }
            Ok(ActionParams::RotateArbiterSet { op, value })
        }
        ACTION_UPDATE_INSURANCE_POOL_PARAMS => {
            let max_coverage_bps = parse_u64(find_kv(&pairs, "max_coverage_bps")?)?;
            let cooldown_sec = parse_u64(find_kv(&pairs, "cooldown_sec")?)?;
            if max_coverage_bps > 10_000 {
                return Err(ERR_INVALID_PARAMS);
            }
            Ok(ActionParams::UpdateInsurancePool {
                max_coverage_bps,
                cooldown_sec,
            })
        }
        ACTION_UPDATE_TIMELOCK_DELAY => {
            let delay_sec = parse_u64(find_kv(&pairs, "delay_sec")?)?;
            if delay_sec < 3600 {
                return Err(ERR_INVALID_PARAMS);
            }
            Ok(ActionParams::UpdateTimelockDelay { delay_sec })
        }
        ACTION_UPDATE_RANGE_PROOF_PARAMS => {
            let min_bits = parse_u64(find_kv(&pairs, "min_bits")?)?;
            let max_bits = parse_u64(find_kv(&pairs, "max_bits")?)?;
            if min_bits == 0 || max_bits == 0 || min_bits > 32 || max_bits > 32 {
                return Err(ERR_INVALID_PARAMS);
            }
            if min_bits > max_bits {
                return Err(ERR_INVALID_PARAMS);
            }
            Ok(ActionParams::UpdateRangeProof { min_bits, max_bits })
        }
        ACTION_PAUSE_PROTOCOL => {
            let mode = find_kv(&pairs, "mode")?;
            let pause = match mode {
                "pause" => true,
                "unpause" => false,
                _ => return Err(ERR_INVALID_PARAMS),
            };
            Ok(ActionParams::PauseProtocol { pause })
        }
        _ => Err(ERR_INVALID_ACTION),
    }
}

// ────────────────────────────────────────────────────────────────────────────
// Execution-attestation message
// ────────────────────────────────────────────────────────────────────────────

/// Byte-parity execution message. The SDK signs this same string; on-chain
/// execute may verify Ed25519 attestations on it (Phase 2 hardening). Even
/// without attestations, hashing this message pins the (id, action, params)
/// tuple into the log for the audit trail.
pub fn build_execution_message(proposal_id: u64, action_type: u64, params: &str) -> String {
    // domain:proposal_id:action_type:params
    let mut m = String::with_capacity(EXECUTION_DOMAIN.len() + params.len() + 48);
    m.push_str(EXECUTION_DOMAIN);
    m.push(':');
    push_u64(&mut m, proposal_id);
    m.push(':');
    push_u64(&mut m, action_type);
    m.push(':');
    m.push_str(params);
    m
}

fn push_u64(out: &mut String, mut n: u64) {
    if n == 0 {
        out.push('0');
        return;
    }
    let mut buf: [u8; 20] = [0; 20];
    let mut i = 0;
    while n > 0 {
        buf[i] = b'0' + (n % 10) as u8;
        n /= 10;
        i += 1;
    }
    while i > 0 {
        i -= 1;
        out.push(buf[i] as char);
    }
}
