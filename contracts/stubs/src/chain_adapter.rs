//! Multi-chain abstraction layer for cross-chain escrow settlement.
//!
//! Planned: Phase 3 — enables escrow bridging between Casper and EVM chains.
//! Current status: interface defined, implementation pending.

use alloc::vec::Vec;

/// Supported blockchain targets for cross-chain operations.
#[derive(Clone, Debug, PartialEq)]
pub enum ChainId {
    CasperTestnet,
    CasperMainnet,
    Ethereum,
    Polygon,
    Arbitrum,
    Custom(u64),
}

/// Result of a remote transaction verification.
pub struct RemoteTxResult {
    pub chain_id: ChainId,
    pub tx_hash: Vec<u8>,
    pub confirmed: bool,
    pub block_number: u64,
}

/// Abstraction for verifying transactions on remote chains.
///
/// Implementors provide chain-specific verification logic.
/// Current: only `CasperAdapter` is implemented (local chain).
pub trait ChainAdapter {
    /// Verify that a transaction exists and is confirmed on the remote chain.
    fn verify_remote_tx(&self, chain_id: &ChainId, tx_hash: &[u8]) -> Result<RemoteTxResult, &'static str>;

    /// Get the current block height on the remote chain.
    fn remote_block_height(&self, chain_id: &ChainId) -> Result<u64, &'static str>;

    /// List supported chains.
    fn supported_chains(&self) -> Vec<ChainId>;
}
