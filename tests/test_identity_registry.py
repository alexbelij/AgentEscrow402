import asyncio
from datetime import datetime
from unittest.mock import patch

import pytest

from server.identity_registry import (
    AgentCapability,
    AgentIdentity,
    DIDResolver,
    IdentityRegistry,
    VerificationLevel,
)


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
        AgentCapability(name="compute", version="1.0", description="Compute capability", verified=True),
        AgentCapability(name="storage", version="2.0", description="Storage capability"),
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
    assert updated.dispute_rate == 1 / 6
    # reputation_score is an int field (see AgentIdentity), so compare
    # against the same rounding the implementation applies rather than the
    # raw float - an int can never equal (5/6)*100 == 83.333... exactly.
    assert updated.reputation_score == round((1 - 1 / 6) * 100)
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
    with patch("server.identity_registry.datetime") as mock_datetime:
        mock_datetime.utcnow.return_value = datetime.fromtimestamp(updated.registered_at + 86400)
        decayed = await registry.apply_decay(identity.did)

    assert decayed.reputation_score < old_score
    # apply_decay only decays reputation_score over time; risk_score is only
    # adjusted by slash() - it intentionally stays unchanged here.
    assert decayed.risk_score == 50


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
    capability = AgentCapability(name="test", version="1.0", description="Test capability")
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
            stake=0,
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

    # model_dump() already contains risk_score - drop it before overriding,
    # otherwise the constructor call raises TypeError (duplicate kwarg)
    # instead of exercising the intended Pydantic range validation.
    dump = identity.model_dump()
    dump.pop("risk_score")

    with pytest.raises(ValueError):
        AgentIdentity(**dump, risk_score=150)


@pytest.mark.asyncio
async def test_stake_field_validation(registry, sample_capabilities):
    account_hash = "abc123"
    identity = await registry.register(account_hash, "Test Agent", sample_capabilities)

    # Test negative stake (see test_risk_score_bounds for why the field
    # must be popped from the dump before being overridden)
    dump = identity.model_dump()
    dump.pop("stake")
    with pytest.raises(ValueError):
        AgentIdentity(**dump, stake=-10)


@pytest.mark.asyncio
async def test_concurrent_registration(registry, sample_capabilities):
    account_hash = "abc123"

    async def register_task():
        return await registry.register(account_hash, "Test Agent", sample_capabilities)

    # Run multiple concurrent registrations
    results = await asyncio.gather(*[register_task() for _ in range(5)], return_exceptions=True)

    # Only one should succeed; asyncio doesn't guarantee *which* positional
    # task wins the lock, only that exactly one does and the rest raise.
    successful = [r for r in results if not isinstance(r, Exception)]
    failed = [r for r in results if isinstance(r, Exception)]
    assert len(successful) == 1
    assert len(failed) == 4
    assert all(isinstance(f, ValueError) for f in failed)


@pytest.mark.asyncio
async def test_last_active_updated_on_reputation_change(registry, sample_capabilities):
    account_hash = "abc123"
    identity = await registry.register(account_hash, "Test Agent", sample_capabilities)
    original_last_active = identity.last_active

    # last_active has whole-second resolution (int(datetime.utcnow().timestamp())),
    # so the sleep must cross a full second boundary to guarantee a difference.
    await asyncio.sleep(1.1)

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


@pytest.mark.asyncio
async def test_get_statistics_empty_registry(registry):
    stats = await registry.get_statistics()
    assert stats == {
        "total_agents": 0,
        "avg_reputation": 0.0,
        "distribution_by_level": {},
    }


@pytest.mark.asyncio
async def test_get_statistics_with_registered_agents(registry, sample_capabilities):
    await registry.register("acct1", "Agent One", sample_capabilities)
    await registry.register("acct2", "Agent Two", sample_capabilities)

    stats = await registry.get_statistics()

    assert stats["total_agents"] == 2
    assert stats["avg_reputation"] == 50.0
    assert stats["distribution_by_level"]["UNVERIFIED"] == 2


class TestDIDResolver:
    def test_parse_did_valid(self):
        assert DIDResolver.parse_did("did:casper:abc123") == ("did", "casper", "abc123")

    def test_parse_did_invalid_format_raises(self):
        with pytest.raises(ValueError):
            DIDResolver.parse_did("not-a-did")

    def test_is_valid_did_true(self):
        assert DIDResolver.is_valid_did("did:casper:abc123") is True

    def test_is_valid_did_false_wrong_method(self):
        assert DIDResolver.is_valid_did("dud:casper:abc123") is False

    def test_is_valid_did_false_wrong_network(self):
        assert DIDResolver.is_valid_did("did:ethereum:abc123") is False

    def test_is_valid_did_false_malformed(self):
        assert DIDResolver.is_valid_did("garbage") is False

    @pytest.mark.asyncio
    async def test_resolve_delegates_to_registry(self, registry, sample_capabilities):
        identity = await registry.register("acct-resolve", "Agent", sample_capabilities)
        resolver = DIDResolver(registry)

        resolved = await resolver.resolve(identity.did)

        assert resolved == identity

    @pytest.mark.asyncio
    async def test_resolve_unknown_did_returns_none(self, registry):
        resolver = DIDResolver(registry)
        assert await resolver.resolve("did:casper:nope") is None
