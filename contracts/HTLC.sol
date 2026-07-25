// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title HTLC — Hash Time-Locked Contract for EVM leg of a cross-chain
///        atomic swap (Tier 3 — T3.4-B).
///
/// Mirrors the semantics of the Python deterministic mock state machine in
/// `server/bridge_htlc.py` (T3.4-A) so both legs of a swap follow identical
/// invariants:
///
///   - `lock()` escrows funds for `recipient`, guarded by `hashlock` and
///     `timelock`.
///   - `claim(preimage)` releases funds to `recipient` iff
///     `sha256(preimage) == hashlock` AND `msg.sender == recipient` AND
///     `block.timestamp < timelock`.
///   - `refund()` returns funds to the original `sender` iff
///     `block.timestamp >= timelock` AND `msg.sender == sender`.
///
/// One contract instance == one HTLC leg (single swap). Deploy a fresh
/// instance per swap leg — this keeps the on-chain state machine as simple
/// and auditable as the Python mock (one `HTLCLeg` per swap side).
///
/// Uses sha256 (not keccak256) for the hashlock so the same preimage/hash
/// pair can be reused verbatim on both the EVM leg and a Casper leg (Casper
/// contracts in this repo hash with sha256 too — see `bridge_htlc.py`).
contract HTLC {
    enum Status { EMPTY, LOCKED, CLAIMED, REFUNDED }

    address public immutable sender;
    address public recipient;
    bytes32 public hashlock;
    uint256 public timelock; // unix seconds, absolute deadline
    uint256 public amount;
    Status public status;

    event Locked(
        address indexed sender,
        address indexed recipient,
        bytes32 hashlock,
        uint256 timelock,
        uint256 amount
    );
    event Claimed(address indexed recipient, bytes preimage);
    event Refunded(address indexed sender);

    error AlreadyLocked();
    error NotLocked();
    error NotRecipient();
    error NotSender();
    error TimelockExpired();
    error TimelockNotExpired();
    error PreimageMismatch();
    error ZeroAmount();
    error ZeroRecipient();
    error TimelockInPast();

    /// @param _recipient address permitted to claim by revealing the preimage
    constructor(address _recipient) {
        sender = msg.sender;
        recipient = _recipient;
        status = Status.EMPTY;
    }

    /// @notice Escrow `msg.value` under `hashlock`, claimable by `recipient`
    ///         before `timelock`, refundable to `sender` at/after `timelock`.
    function lock(bytes32 _hashlock, uint256 _timelock) external payable {
        if (status != Status.EMPTY) revert AlreadyLocked();
        if (msg.value == 0) revert ZeroAmount();
        if (recipient == address(0)) revert ZeroRecipient();
        if (_timelock <= block.timestamp) revert TimelockInPast();

        hashlock = _hashlock;
        timelock = _timelock;
        amount = msg.value;
        status = Status.LOCKED;

        emit Locked(sender, recipient, _hashlock, _timelock, msg.value);
    }

    /// @notice Reveal `preimage` to claim the escrowed funds. Permissionless
    ///         to compute, but only `recipient` may receive the payout.
    function claim(bytes memory preimage) external {
        if (status != Status.LOCKED) revert NotLocked();
        if (msg.sender != recipient) revert NotRecipient();
        if (block.timestamp >= timelock) revert TimelockExpired();
        if (sha256(preimage) != hashlock) revert PreimageMismatch();

        status = Status.CLAIMED;
        uint256 payout = amount;
        amount = 0;

        emit Claimed(msg.sender, preimage);
        (bool ok, ) = payable(msg.sender).call{value: payout}("");
        require(ok, "transfer failed");
    }

    /// @notice Return escrowed funds to `sender` once `timelock` has passed
    ///         without a successful claim.
    function refund() external {
        if (status != Status.LOCKED) revert NotLocked();
        if (msg.sender != sender) revert NotSender();
        if (block.timestamp < timelock) revert TimelockNotExpired();

        status = Status.REFUNDED;
        uint256 payout = amount;
        amount = 0;

        emit Refunded(msg.sender);
        (bool ok, ) = payable(msg.sender).call{value: payout}("");
        require(ok, "transfer failed");
    }

    /// @notice View helper mirroring `bridge_htlc.py` leg status dict.
    function getStatus()
        external
        view
        returns (
            address _sender,
            address _recipient,
            bytes32 _hashlock,
            uint256 _timelock,
            uint256 _amount,
            Status _status
        )
    {
        return (sender, recipient, hashlock, timelock, amount, status);
    }
}
