//! On-chain Agent Identity Registry for AI agent discovery and reputation.
//!
//! Based on ERC-8004/ERC-8126 standards adapted for Casper Network.
//! Agents register with DID (did:casper:{network}:{account_hash}),
//! declare capabilities, and stake CSPR as anti-Sybil protection.
//!
//! Planned: Phase 2 — on-chain DID + capabilities + staking.

use alloc::string::String;
use alloc::vec::Vec;

/// Minimum stake required to register an agent (in motes).
pub const MIN_STAKE_MOTES: u64 = 100_000_000_000; // 100 CSPR

/// Cooldown period after deregistration before stake return (seconds).
pub const DEREGISTER_COOLDOWN_SECS: u64 = 604800; // 7 days

/// Weekly reputation decay for inactive agents.
pub const REPUTATION_DECAY_PER_WEEK: u8 = 1;

/// Agent capabilities that can be advertised in the registry.
#[derive(Clone, Debug, PartialEq)]
pub enum Capability {
    Inference,
    DataProcessing,
    Translation,
    ContentGeneration,
    Arbitration,
    Custom(String),
}

/// Verification level for an agent's identity.
#[derive(Clone, Debug, PartialEq, Ord, PartialOrd, Eq)]
pub enum VerificationLevel {
    SelfDeclared = 0,
    PeerVerified = 1,
    OracleVerified = 2,
    FormallyVerified = 3,
}

/// On-chain agent identity record.
#[derive(Clone, Debug)]
pub struct AgentRecord {
    /// Decentralized identifier: did:casper:{network}:{account_hash}
    pub did: String,
    /// Account hash of the owner on Casper.
    pub owner: [u8; 32],
    /// Declared capabilities.
    pub capabilities: Vec<Capability>,
    /// Staked amount in motes.
    pub stake: u64,
    /// Reputation score (0-100).
    pub reputation: u8,
    /// Verification level.
    pub verification_level: VerificationLevel,
    /// Unix timestamp of registration.
    pub registered_at: u64,
    /// Unix timestamp of last activity.
    pub last_active: u64,
}

impl AgentRecord {
    /// Apply weekly reputation decay.
    pub fn apply_decay(&mut self, current_time: u64) {
        let weeks_inactive = (current_time.saturating_sub(self.last_active)) / 604800;
        let decay = (weeks_inactive as u8).saturating_mul(REPUTATION_DECAY_PER_WEEK);
        self.reputation = self.reputation.saturating_sub(decay);
    }
}
