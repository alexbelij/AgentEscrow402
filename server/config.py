"""Application configuration."""

from __future__ import annotations

import base64
import os
import tempfile
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    casper_node_url: str = ""
    casper_chain_name: str = "casper-test"
    nownodes_api_key: str = ""
    casper_private_key_path: str = ""
    host: str = "0.0.0.0"
    port: int = 8000
    sandbox: bool = True
    default_ttl: int = 300
    insurance_fee_bps: int = 200  # 2% = 200 basis points
    contract_hash: str = ""
    manager_contract_hash: str = ""
    insurance_contract_hash: str = ""
    # Package hash (not contract hash) of the insurance-pool contract --
    # required by the pool-funder session-wasm's `deposit()` cross-contract
    # call (runtime::call_versioned_contract needs the package, not the
    # contract, hash). See contracts/pool-funder/src/main.rs.
    insurance_package_hash: str = ""
    vrf_contract_hash: str = ""
    # Package hash (not contract hash) of the vrf-arbiter contract --
    # required by the arbiter-registrar session-wasm's `call_versioned_contract`
    # cross-contract call into `register_arbiter()`. See
    # contracts/arbiter-registrar/src/main.rs.
    vrf_package_hash: str = ""
    # Number of candidates requested from the on-chain `select_arbiters`
    # entry point per election. Requesting more than 1 gives the backend
    # room to apply INVARIANT 5 (arbiter != either dispute party) locally,
    # since the contract's own `select_arbiters` has no knowledge of dispute
    # parties and cannot exclude them itself.
    multi_asset_escrow_contract_hash: str = ""
    multi_asset_escrow_package_hash: str = ""
    test_token_contract_hash: str = ""
    # CEP-18 test token used to prefill the "contract hash" field for CEP-18
    # escrow/permit demos. Previously hardcoded as TEST_CEP18_CONTRACT_HASH
    # directly in frontend/src/lib/api.ts with no config/manifest wiring.
    cep18_aetusd_contract_hash: str = ""
    # CEP-78 test NFT used for multi-asset escrow NFT demos. Previously
    # hardcoded in three places (frontend/src/components/TrustSignals.tsx,
    # frontend/src/components/console/Contracts.tsx, and this endpoint) with
    # no manifest entry to verify it against -- see deploy-out/onchain.json
    # "cep78_test_token_aetnft" for the verified source of truth.
    aetnft_contract_hash: str = ""
    # Was hardcoded directly in the /contracts response below; every other
    # deployed contract hash here is env-overridable so a redeploy never
    # requires a code change.
    agent_identity_contract_hash: str = ""
    # Casper leg of the ROADMAP L85 multi-chain HTLC bridge. Deployed
    # 2026-07-26 (see deploy-out/onchain.json "casper_htlc") but never wired
    # into this Config or the /contracts response, so the console's
    # "Contracts" tab silently showed 9/10 live contracts instead of 10/10.
    htlc_contract_hash: str = ""
    vrf_onchain_select_count: int = 3
    allow_hosted_demo_identity: bool = False
    # Hex-encoded (tag-prefixed) Ed25519 public keys of the registered
    # arbiters, mirroring the on-chain `arbiter_list`. Used to verify
    # arbiter vote signatures locally in sandbox mode (live mode relies on
    # the contract's own on-chain verification, but checking here too gives
    # callers a fast, clear 4xx instead of waiting for an on-chain revert).
    arbiter_pubkeys: tuple[str, ...] = ()
    arbiter_threshold: int = 3
    # A1 hardening: mirrors the on-chain `release_cap` default (see
    # DEFAULT_RELEASE_CAP_MOTES in contracts/escrow/src/main.rs). Used only
    # for the backend's fast-fail check in /release and /escrow/atomic-swap/
    # reveal; the contract's own on-chain value is authoritative. Keep in
    # sync if set_release_cap() is ever called to change the on-chain cap.
    release_cap_motes: int = 1_000_000_000_000
    # T2.12 flash-loan protection (server/flash_guard.py). Off by default so
    # the sandbox/demo path (instant create->release in one script run)
    # keeps working out of the box; set FLASH_GUARD_ENABLED=true for any
    # environment that faces real counterparties. See flash_guard.py for
    # why this is enforced server-side today, with an on-chain port
    # tracked as follow-up (same pattern as batch_guard.py / T3.3).
    flash_guard_enabled: bool = False
    # Shared secret required (via X-Admin-Key header) to reach the
    # installer-only admin routes (configure_fee/set_release_cap/
    # set_arbiters/emergency_freeze). Empty by default => those routes are
    # disabled (fail closed), not open, until explicitly configured.
    admin_api_key: str = ""
    # Account hash of the backend's own operator/deployer key (the account
    # that pays gas as the "spender"/relayer in the CEP-18 gasless permit
    # flow -- see CasperClient.cep18_permit/cep18_transfer_from). Derived
    # once from alexbelij_secret_key.pem via casper-js-sdk; update if the
    # operator key is ever rotated.
    casper_operator_account_hash: str = "74c96cd0073c4c973b70e7925adca8a4ba58ffcb9737304631381b82695007a8"
    # Strict / fail-loud mode. When AE402_STRICT=1 in the environment, any
    # code path that would ordinarily silently fall back to sandbox / demo /
    # mock behaviour must instead raise StrictModeError. The purpose is to
    # make production configuration mistakes (missing key, wrong RPC, empty
    # contract hash, RPC 5xx, DB down) crash loudly rather than serve fake
    # results. Judges / operators enabling this flag get a guarantee that a
    # 200 response means the write actually reached testnet.
    #
    # The well-known preconditions checked at startup (see
    # Config.require_strict_preconditions()) are:
    #   - casper_node_url non-empty
    #   - contract_hash non-empty
    #   - sandbox is False
    #   - casper_private_key_path non-empty (server/app.py only constructs a
    #     live CasperClient when all of sandbox=false, casper_node_url and
    #     casper_private_key_path are set -- without this check a strict app
    #     missing only the key would still silently fall through to the
    #     None-casper-client / SandboxStore branch on every request)
    # A running app under AE402_STRICT=1 additionally raises StrictModeError
    # in every code path that ships a "silent fallback" branch.
    strict_mode: bool = False
    # Root secret for the Macaroon capability layer (see sdk/macaroons.py
    # and server/macaroon_api.py). Accepts base64url or hex; must decode to
    # >=24 bytes. Empty by default — the /macaroons/* endpoints fail closed
    # with 503 until this is configured, so misconfigured deployments never
    # accept macaroon-authenticated calls.
    macaroon_root_secret: str = ""

    @classmethod
    def from_env(cls) -> Config:
        key_path = os.getenv("CASPER_PRIVATE_KEY_PATH", "")

        # Support DEPLOYER_KEY_B64 — decode to temp file
        key_b64 = os.getenv("DEPLOYER_KEY_B64", "")
        if key_b64 and not key_path:
            raw = base64.b64decode(key_b64)
            fd, key_path = tempfile.mkstemp(suffix=".pem", prefix="deployer_")
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
            os.chmod(key_path, 0o600)

        sandbox_str = os.getenv("SANDBOX", "true").lower()
        sandbox = sandbox_str == "true"

        return cls(
            casper_node_url=os.getenv("CASPER_NODE_URL", ""),
            casper_chain_name=os.getenv("CASPER_CHAIN_NAME", os.getenv("CASPER_CHAIN", "casper-test")),
            nownodes_api_key=os.getenv("NOWNODES_API_KEY", ""),
            casper_private_key_path=key_path,
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "8000")),
            sandbox=sandbox,
            default_ttl=int(os.getenv("DEFAULT_TTL", "300")),
            insurance_fee_bps=int(os.getenv("INSURANCE_FEE_BPS", "200")),
            contract_hash=os.getenv("ESCROW_CONTRACT_HASH", ""),
            # Deployed once, rarely redeployed; env-overridable so a future
            # redeploy of any of these never requires a frontend code change
            # (previously hardcoded in frontend/src/components/console/Contracts.tsx).
            manager_contract_hash=os.getenv(
                "MANAGER_CONTRACT_HASH",
                # 2026-07-26 redeploy (v11): adds link_escrows / get_link
                # entry points for on-chain multi-hop A2A intent linking.
                # Deployer: alexbelij (account-hash 74c96cd0...07a8), Casper
                # testnet block 8633133, deploy hash
                # 1b600ef544752ba07e66de2be724ab660bcfb18fde83e440a6697a501ced3bce.
                # New package hash:
                # 1b93d536947da31ed80d6b57a5db74c718b6cf08f33e5b0bdd893d27f481dd0c.
                # Previous v1 (bfa8c02c...) still lives on-chain but is
                # frozen — new integrations should point at v11.
                "c423a07f334ae4c5badf7fcfe6c595abc1d7ba07fdfc43a0464525aa416fe4d6",
            ),
            insurance_contract_hash=os.getenv(
                "INSURANCE_CONTRACT_HASH",
                # ead90738... is the redeployed insurance-pool contract
                # (2026-07-18, deploy 74ce85ac...096) with:
                #   * A1: arbiter-quorum fix on claim()/withdraw() (the previous
                #     e36b958d... contract, now superseded, had a fully public
                #     claim()/withdraw()).
                #   * Insurance-replay guard: global claimed_escrow_ids dict,
                #     tombstone-before-payout, atomic revert (commit ab17a1b).
                # Old e128780f... (superseded by this deploy) still lingers in
                # Render prod env vars -- see docs/DEPLOYMENT_LESSONS.md open items.
                "ead90738d19ad7fcc88c9e079e12d8cf6d4fd09ddd3daafe565bf4fe4b95fff4",
            ),
            insurance_package_hash=os.getenv(
                "INSURANCE_PACKAGE_HASH",
                "78258f66b1ae08120f9c10186ce88772d92d2f84561ca8aa68cb8ffcc6d67f97",
            ),
            vrf_contract_hash=os.getenv(
                "VRF_CONTRACT_HASH",
                # 78ae2870... is the redeployed vrf-arbiter contract with the
                # register_arbiter() session-arg fix (top-level "amount" arg
                # required by the node's Mint ARG_AMOUNT spending-limit check;
                # see contracts/arbiter-registrar/src/main.rs commit history).
                # The old 5d65bedf... contract's register_arbiter() write path
                # always failed with Mint error 21 (UnapprovedSpendingAmount).
                "78ae28702deeb2eadec573d95b870f68b928a82a3566e292ff33a9ae2c779c93",
            ),
            vrf_package_hash=os.getenv(
                "VRF_PACKAGE_HASH",
                "53805f7866cd158ff091ab93efe2f19bd2e803414a5ef1badc7a46d759f36611",
            ),
            multi_asset_escrow_contract_hash=os.getenv(
                "MULTI_ASSET_ESCROW_CONTRACT_HASH",
                # Key-fix redeploy 2026-07-24 (into_entity_hash_addr for Casper
                # 2.0 compat, fix commit a9d7071); see deploy-out/onchain.json.
                "8080845bad4f12c4a720dd96551dc64d116208aa71e0ce1410b75afca8e8eb61",
            ),
            multi_asset_escrow_package_hash=os.getenv(
                "MULTI_ASSET_ESCROW_PACKAGE_HASH",
                "a3207e9bb29f6cec6c5017e6c7538626f92f001d35cda22585dff9f76a488044",
            ),
            test_token_contract_hash=os.getenv(
                "TEST_TOKEN_CONTRACT_HASH",
                # Key-fix redeploy 2026-07-24 (into_entity_hash_addr for Casper
                # 2.0 compat, fix commit a9d7071); see deploy-out/onchain.json
                # "cep18_test_token_aemat".
                "2e319caa09768162144fed4c53f0259ef733ffd97e56a107064026022ac0377b",
            ),
            cep18_aetusd_contract_hash=os.getenv(
                "CEP18_AETUSD_CONTRACT_HASH",
                "177ca5d88f72e1ca72fbe94a24ba34b03830dd1fe63d90d3d719cd6e6d4de754",
            ),
            aetnft_contract_hash=os.getenv(
                "AETNFT_CONTRACT_HASH",
                # Verified against CSPR.cloud contract-packages/contracts on
                # 2026-07-24; see deploy-out/onchain.json
                # "cep78_test_token_aetnft" for the canonical record.
                "c2dee0f1f40c3dae3f3106f70d69b8768d7426758b43040673f68e271f2bf70a",
            ),
            macaroon_root_secret=os.getenv("MACAROON_ROOT_SECRET", ""),
            agent_identity_contract_hash=os.getenv(
                "AGENT_IDENTITY_CONTRACT_HASH",
                # Key-fix redeploy 2026-07-24 (into_entity_hash_addr for Casper
                # 2.0 compat, fix commit a9d7071); see deploy-out/onchain.json.
                "345c179cd28eae46bfcda5cd4d8b9192d631593f936af85ccfe3a2cece5c7b1f",
            ),
            htlc_contract_hash=os.getenv(
                "HTLC_CONTRACT_HASH",
                # Deployed 2026-07-26; see deploy-out/onchain.json "casper_htlc".
                "5d5a8d79bd37841234cc9c814937609974715fce214ac814e78eb7528ea0a435",
            ),
            vrf_onchain_select_count=int(os.getenv("VRF_ONCHAIN_SELECT_COUNT", "3")),
            allow_hosted_demo_identity=os.getenv("ALLOW_HOSTED_DEMO_IDENTITY", "false").lower() == "true",
            flash_guard_enabled=os.getenv("FLASH_GUARD_ENABLED", "false").lower() == "true",
            arbiter_pubkeys=tuple(p.strip() for p in os.getenv("ARBITER_PUBKEYS", "").split(",") if p.strip()),
            arbiter_threshold=int(os.getenv("ARBITER_THRESHOLD", "3")),
            release_cap_motes=int(os.getenv("RELEASE_CAP_MOTES", "1000000000000")),
            admin_api_key=os.getenv("ADMIN_API_KEY", ""),
            casper_operator_account_hash=os.getenv(
                "CASPER_OPERATOR_ACCOUNT_HASH",
                "74c96cd0073c4c973b70e7925adca8a4ba58ffcb9737304631381b82695007a8",
            ),
            strict_mode=os.getenv("AE402_STRICT", "0") == "1",
        )

    def require_strict_preconditions(self) -> list[str]:
        """Return a list of strict-mode precondition violations.

        Used at startup and by /health to expose the strict-mode readiness
        picture. An empty list means the app is safe to run under strict
        mode; a non-empty list means starting up under AE402_STRICT=1 will
        raise StrictModeError.
        """
        violations: list[str] = []
        if not self.casper_node_url:
            violations.append("casper_node_url is empty (set CASPER_NODE_URL)")
        if not self.contract_hash:
            violations.append("contract_hash is empty (set ESCROW_CONTRACT_HASH)")
        if self.sandbox:
            violations.append("sandbox=true (set SANDBOX=false for live mode)")
        if not self.casper_private_key_path:
            # server/app.py only constructs a live CasperClient when
            # `not sandbox and casper_node_url and casper_private_key_path`
            # are ALL set; before this check, a strict-mode app with
            # casper_node_url/contract_hash/sandbox=false but no key would
            # pass this precondition gate yet still fall through to the
            # None-casper-client / SandboxStore branch on every request --
            # exactly the "green 200, nothing hit testnet" failure strict
            # mode exists to prevent. See tests/test_strict_mode.py.
            violations.append("casper_private_key_path is empty (set CASPER_PRIVATE_KEY_PATH or DEPLOYER_KEY_B64)")
        return violations

    def strict_mode_capabilities(self) -> dict[str, object]:
        """Structured capability breakdown for /health.

        Returns a dict with:
          - enabled: bool -- whether AE402_STRICT=1
          - preconditions_ok: bool -- whether all preconditions are satisfied
          - violations: list[str] -- specific issues (empty if preconditions_ok)
          - guarantees: list[str] -- what a 200 response means under strict mode
        """
        violations = self.require_strict_preconditions()
        return {
            "enabled": self.strict_mode,
            "preconditions_ok": len(violations) == 0,
            "violations": violations,
            "guarantees": (
                [
                    "any RPC failure raises hard error instead of silent fallback",
                    "missing contract hash raises hard error at request time",
                    "missing private key raises hard error before submitting",
                    "DB write failure propagates as 5xx (no in-memory-only claims)",
                ]
                if self.strict_mode
                else []
            ),
        }


def get_config() -> Config:
    """Dependency injection helper for FastAPI."""
    return Config.from_env()
