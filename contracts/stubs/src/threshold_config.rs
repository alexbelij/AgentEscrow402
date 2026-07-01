//! MPC threshold configuration for multi-party escrow release.
//!
//! Planned: Phase 3 — Shamir Secret Sharing for n-of-m signatures.
//! Current status: data structures defined, crypto implementation pending.

/// Configuration for threshold-based escrow operations.
///
/// Enables n-of-m signature schemes where `min_signers` out of
/// `total_signers` must approve a release or dispute resolution.
#[derive(Clone, Debug)]
pub struct ThresholdConfig {
    /// Minimum number of signers required to approve an action.
    pub min_signers: u32,
    /// Total number of authorized signers.
    pub total_signers: u32,
    /// Whether MPC key generation has been completed.
    pub setup_complete: bool,
    /// Timeout in seconds for collecting signatures.
    pub collection_timeout_secs: u64,
}

impl ThresholdConfig {
    pub fn new(min_signers: u32, total_signers: u32) -> Result<Self, &'static str> {
        if min_signers == 0 || min_signers > total_signers {
            return Err("invalid threshold: min_signers must be in [1, total_signers]");
        }
        Ok(Self {
            min_signers,
            total_signers,
            setup_complete: false,
            collection_timeout_secs: 3600,
        })
    }

    pub fn is_quorum(&self, collected: u32) -> bool {
        collected >= self.min_signers
    }
}
