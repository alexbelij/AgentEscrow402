import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from server.identity_registry import (
    IdentityRegistry,
    AgentIdentity,
    AgentCapability,
    VerificationLevel
)
import asyncio

@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def registry(event_loop):
    return IdentityRegistry(decay_interval=86400, decay_rate=0.01)

@pytest.fixture
def sample_capabilities():
    return [
        AgentCapability(
            name="compute",
            version="1.0",
            description="Compute capability",
            verified=True
        ),
        AgentCapability(
            name="storage",
            version="2.0",
            description="Storage capability"
        )
    ]

@pytest.mark.asyncio
async def test_register_new_identity(registry, sample_capabilities):
    account_hash = "abc123"
    display_name = "Test Agent"
    identity = await registry.register(account_hash, display_name, sample_capabilities)

    assert identity.did == f"did:casper:{account_hash}"
    assert identity.account_hash == account_hash
    assert identity.display_name == display_name
    assert len(identity.capabilities) == 2
    assert identity.verification_level == VerificationLevel.UNVERIFIED
    assert identity.reputation_score == 50
    assert identity.total_deals == 0
    assert identity.dispute_rate == 0.0
    assert identity.risk_score == 50
    assert identity.slashed_count == 0
    assert identity.stake == 0
    assert identity.metadata_hash != ""

@pytest.mark.asyncio
async def test_register_duplicate_account(registry, sample_capabilities):
    account_hash = "abc123"
    await registry.register(account_hash, "Test Agent", sample_capabilities)

    with pytest.raises(ValueError, match="Account already registered"):
        await registry.register(account_hash, "Another Agent", sample_capabilities)

@pytest.mark.asyncio
async def test_register_without_capabilities(registry):
    account_hash = "xyz789"
    display_name = "Minimal Agent"
    identity = await registry.register(account_hash, display_name)

    assert identity.did == f"did:casper:{account_hash}"
    assert identity.account_hash == account_hash
    assert identity.display_name == display_name
    assert identity.capabilities == []
    assert identity.verification_level == VerificationLevel.UNVERIFIED

@pytest.mark.asyncio
async def test_get_existing_identity(registry, sample_capabilities):
    account_hash = "abc123"
    identity = await registry.register(account_hash, "Test Agent", sample_capabilities)

    retrieved = await registry.get(identity.did)
    assert retrieved == identity

@pytest.mark.asyncio
async def test_get_nonexistent_identity(registry):
    retrieved = await registry.get("did:casper:nonexistent")
    assert retrieved is None

@pytest.mark.asyncio
async def test_get_by_account_existing(registry, sample_capabilities):
    account_hash = "abc123"
    identity = await registry.register(account_hash, "Test Agent", sample_capabilities)

    retrieved = await registry.get_by_account(account_hash)
    assert retrieved == identity

@pytest.mark.asyncio
async def test_get_by_account_nonexistent(registry):
    retrieved = await registry.get_by_account("nonexistent")
    assert retrieved is None

@pytest.mark.asyncio
async def test_update_reputation_with_new_deals(registry, sample_capabilities):
    account_hash = "abc123"
    identity = await registry.register(account_hash, "Test Agent", sample_capabilities)

    updated = await registry.update_reputation(identity.did, completed=5, disputed=1)

    assert updated.total_deals == 6
    assert updated.dispute_rate == 1/6
    assert updated.reputation_score == (5/6)*100
    assert updated.last_active == updated.registered_at

@pytest.mark.asyncio
async def test_update_reputation_no_new_deals(registry, sample_capabilities):
    account_hash = "abc123"
    identity = await registry.register(account_hash, "Test Agent", sample_capabilities)

    updated = await registry.update_reputation(identity.did)

    assert updated.total_deals == 0
    assert updated.dispute_rate == 0.0
    assert updated.reputation_score == 50  # unchanged

@pytest.mark.asyncio
async def test_update_reputation_nonexistent_identity(registry):
    with pytest.raises(ValueError, match="Identity not found"):
        await registry.update_reputation("did:casper:nonexistent", completed=1)

@pytest.mark.asyncio
async def test_update_reputation_max_score(registry, sample_capabilities):
    account_hash = "abc123"
    identity = await registry.register(account_hash, "Test Agent", sample_capabilities)

    updated = await registry.update_reputation(identity.did, completed=100, disputed=0)

    assert updated.reputation_score == 100

@pytest.mark.asyncio
async def test_update_reputation_min_score(registry, sample_capabilities):
    account_hash = "abc123"
    identity = await registry.register(account_hash, "Test Agent", sample_capabilities)

    updated = await registry.update_reputation(identity.did, completed=0, disputed=100)

    assert updated.reputation_score == 0

@pytest.mark.asyncio
async def test_apply_decay_updates_scores(registry, sample_capabilities):
    account_hash = "abc123"
    identity = await registry.register(account_hash, "Test Agent", sample_capabilities)

    # Update reputation to a known state
    updated = await registry.update_reputation(identity.did, completed=10, disputed=2)
    old_score = updated.reputation_score

    # Mock time to control decay application
    with patch('server.identity_registry.datetime') as mock_datetime:
        mock_datetime.utcnow.return_value = datetime.fromtimestamp(updated.registered_at + 86400)
        decayed = await registry.apply_decay(identity.did)

    assert decayed.reputation_score < old_score
    assert decayed.risk_score != 50

@pytest.mark.asyncio
async def test_apply_decay_nonexistent_identity(registry):
    with pytest.raises(ValueError, match="Identity not found"):
        await registry.apply_decay("did:casper:nonexistent")

@pytest.mark.asyncio
async def test_metadata_hash_changes_on_update(registry, sample_capabilities):
    account_hash = "abc123"
    identity = await registry.register(account_hash, "Test Agent", sample_capabilities)
    original_hash = identity.metadata_hash

    updated = await registry.update_reputation(identity.did, completed=1)
    assert updated.metadata_hash != original_hash

@pytest.mark.asyncio
async def test_capability_validation(registry):
    capability = AgentCapability(
        name="test",
        version="1.0",
        description="Test capability"
    )
    assert capability.verified is False

@pytest.mark.asyncio
async def test_verification_level_enum():
    assert VerificationLevel.UNVERIFIED.value == "UNVERIFIED"
    assert VerificationLevel.BASIC.value == "BASIC"
    assert VerificationLevel.ENHANCED.value == "ENHANCED"
    assert VerificationLevel.FULL.value == "FULL"

@pytest.mark.asyncio
async def test_did_validation_with_invalid_did(registry):
    with pytest.raises(ValueError, match="DID must start with 'did:casper:'"):
        AgentIdentity(
            did="invalid:did",
            account_hash="abc123",
            display_name="Test",
            capabilities=[],
            verification_level=VerificationLevel.UNVERIFIED,
            reputation_score=50,
            total_deals=0,
            dispute_rate=0.0,
            registered_at=int(datetime.utcnow().timestamp()),
            last_active=int(datetime.utcnow().timestamp()),
            metadata_hash="",
            risk_score=50,
            slashed_count=0,
            stake=0
        )

@pytest.mark.asyncio
async def test_reputation_score_bounds(registry, sample_capabilities):
    account_hash = "abc123"
    identity = await registry.register(account_hash, "Test Agent", sample_capabilities)

    # Test upper bound
    updated = await registry.update_reputation(identity.did, completed=1000)
    assert updated.reputation_score == 100

    # Test lower bound
    updated = await registry.update_reputation(identity.did, completed=0, disputed=1000)
    assert updated.reputation_score == 0

@pytest.mark.asyncio
async def test_risk_score_bounds(registry, sample_capabilities):
    account_hash = "abc123"
    identity = await registry.register(account_hash, "Test Agent", sample_capabilities)

    # Manually set risk score to test bounds
    identity.risk_score = 150
    registry._identities[identity.did] = identity

    with pytest.raises(ValueError):
        AgentIdentity(
            **identity.model_dump(),
            risk_score=150
        )

@pytest.mark.asyncio
async def test_stake_field_validation(registry, sample_capabilities):
    account_hash = "abc123"
    identity = await registry.register(account_hash, "Test Agent", sample_capabilities)

    # Test negative stake
    with pytest.raises(ValueError):
        AgentIdentity(
            **identity.model_dump(),
            stake=-10
        )

@pytest.mark.asyncio
async def test_concurrent_registration(registry, sample_capabilities):
    account_hash = "abc123"

    async def register_task():
        return await registry.register(account_hash, "Test Agent", sample_capabilities)

    # Run multiple concurrent registrations
    results = await asyncio.gather(*[register_task() for _ in range(5)], return_exceptions=True)

    # Only one should succeed
    successful = [r for r in results if not isinstance(r, Exception)]
    assert len(successful) == 1
    assert isinstance(results[0], ValueError)  # Others should fail

@pytest.mark.asyncio
async def test_last_active_updated_on_reputation_change(registry, sample_capabilities):
    account_hash = "abc123"
    identity = await registry.register(account_hash, "Test Agent", sample_capabilities)
    original_last_active = identity.last_active

    await asyncio.sleep(0.1)  # Ensure time difference

    updated = await registry.update_reputation(identity.did, completed=1)
    assert updated.last_active > original_last_active

@pytest.mark.asyncio
async def test_empty_display_name(registry):
    account_hash = "abc123"
    identity = await registry.register(account_hash, "")
    assert identity.display_name == ""

@pytest.mark.asyncio
async def test_capability_with_empty_fields(registry):
    capability = AgentCapability(name="", version="", description="")
    assert capability.name == ""
    assert capability.version == ""
    assert capability.description == ""
    assert capability.verified is False

@pytest.mark.asyncio
async def test_decay_interval_and_rate_properties(registry):
    assert registry._decay_interval == 86400
    assert registry._decay_rate == 0.01

    new_registry = IdentityRegistry(decay_interval=3600, decay_rate=0.05)
    assert new_registry._decay_interval == 3600
    assert new_registry._decay_rate == 0.05

@pytest.mark.asyncio
async def test_identity_equality(registry, sample_capabilities):
    account_hash = "abc123"
    identity1 = await registry.register(account_hash, "Test Agent", sample_capabilities)
    identity2 = await registry.get(identity1.did)

    assert identity1 == identity2

@pytest.mark.asyncio
async def test_metadata_hash_format(registry, sample_capabilities):
    account_hash = "abc123"
    identity = await registry.register(account_hash, "Test Agent", sample_capabilities)
    assert len(identity.metadata_hash) == 64  # SHA-256 hash length
    assert all(c in "0123456789abcdef" for c in identity.metadata_hash)
