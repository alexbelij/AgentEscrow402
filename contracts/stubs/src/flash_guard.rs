//! Flash loan protection for escrow operations.
//!
//! Prevents manipulation via flash-borrowed funds by enforcing
//! minimum hold periods and block delays.

/// Minimum number of blocks between fund and release.
pub const MIN_BLOCK_DELAY: u64 = 5;

/// Minimum hold period in seconds before release is allowed.
pub const MIN_HOLD_PERIOD_SECS: u64 = 300; // 5 minutes

/// Check whether sufficient time has passed since escrow funding.
pub fn check_hold_period(funded_at: u64, current_time: u64) -> Result<(), &'static str> {
    let elapsed = current_time.saturating_sub(funded_at);
    if elapsed < MIN_HOLD_PERIOD_SECS {
        return Err("flash guard: hold period not met");
    }
    Ok(())
}

/// Check whether sufficient blocks have passed since funding.
pub fn check_block_delay(funded_block: u64, current_block: u64) -> Result<(), &'static str> {
    let blocks = current_block.saturating_sub(funded_block);
    if blocks < MIN_BLOCK_DELAY {
        return Err("flash guard: block delay not met");
    }
    Ok(())
}
