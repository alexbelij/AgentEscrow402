// GENERATED FILE -- do not edit by hand.
// Source of truth: deploy-out/onchain.json
// Regenerate with: python3 scripts/generate_frontend_manifest.py
// Verified in CI by tests/test_manifest_frontend_config_sync.py


export const NETWORK = "casper-test";
export const MANIFEST_GENERATED_AT = "2026-07-26T19:40:00Z";
export const API_URL = "https://agentescrow402-api-ywm8.onrender.com";
export const FRONTEND_URL = "https://ae402.xyz";

export interface ManifestContract {
  key: string;
  name: string;
  contractHash: string;
  contractPackageHash: string;
  deployHash: string;
  version: number;
  explorer: string;
}

export const CONTRACTS: Record<string, ManifestContract> = {
  escrowManagerV9: {
    key: "escrow_manager_v9",
    name: "Core Escrow",
    contractHash: "07527a37742b4da87c9cc38baf752f53b1525b53d0825269d9952a3813739ef1",
    contractPackageHash: "d3ca33d192dda5ece798db91811ec1259d2197ca0e8d3ea4de043b977d3c8eeb",
    deployHash: "ce65b0a5120aab3fc47766daf5f6cea3ed3f491e7b45e31208ee8f2a8aa16862",
    version: 10,
    explorer: "https://testnet.cspr.live/contract/07527a37742b4da87c9cc38baf752f53b1525b53d0825269d9952a3813739ef1",
  },
  batchEscrowManager: {
    key: "batch_escrow_manager",
    name: "Escrow Manager",
    contractHash: "c423a07f334ae4c5badf7fcfe6c595abc1d7ba07fdfc43a0464525aa416fe4d6",
    contractPackageHash: "1b93d536947da31ed80d6b57a5db74c718b6cf08f33e5b0bdd893d27f481dd0c",
    deployHash: "1b600ef544752ba07e66de2be724ab660bcfb18fde83e440a6697a501ced3bce",
    version: 11,
    explorer: "https://testnet.cspr.live/contract/c423a07f334ae4c5badf7fcfe6c595abc1d7ba07fdfc43a0464525aa416fe4d6",
  },
  insurancePool: {
    key: "insurance_pool",
    name: "Insurance Pool",
    contractHash: "ead90738d19ad7fcc88c9e079e12d8cf6d4fd09ddd3daafe565bf4fe4b95fff4",
    contractPackageHash: "78258f66b1ae08120f9c10186ce88772d92d2f84561ca8aa68cb8ffcc6d67f97",
    deployHash: "4ea886beee6c1d302a4282c11390856da8ae89e6a05775e57bb6c5e7dae0b16f",
    version: 1,
    explorer: "https://testnet.cspr.live/contract/ead90738d19ad7fcc88c9e079e12d8cf6d4fd09ddd3daafe565bf4fe4b95fff4",
  },
  vrfArbiter: {
    key: "vrf_arbiter",
    name: "VRF Arbiter",
    contractHash: "78ae28702deeb2eadec573d95b870f68b928a82a3566e292ff33a9ae2c779c93",
    contractPackageHash: "53805f7866cd158ff091ab93efe2f19bd2e803414a5ef1badc7a46d759f36611",
    deployHash: "83babe5d1d0c80aff7e2f8edd62e3898bf175a6c6c495b5fafa9f7692de14e27",
    version: 1,
    explorer: "https://testnet.cspr.live/contract/78ae28702deeb2eadec573d95b870f68b928a82a3566e292ff33a9ae2c779c93",
  },
  agentIdentityRegistry: {
    key: "agent_identity_registry",
    name: "Agent Identity Registry (ID-1)",
    contractHash: "345c179cd28eae46bfcda5cd4d8b9192d631593f936af85ccfe3a2cece5c7b1f",
    contractPackageHash: "0b760bb7bf9be5a74ee4ed5626bcc74a8154f221a059e29fc9d768d45fb4a2ba",
    deployHash: "4ce05bb49b9e5c69447547bc27ad6ea7b715dcdfc7a10bd3b6fd0fafdcd3e865",
    version: 3,
    explorer: "https://testnet.cspr.live/contract/345c179cd28eae46bfcda5cd4d8b9192d631593f936af85ccfe3a2cece5c7b1f",
  },
  multiAssetEscrow: {
    key: "multi_asset_escrow",
    name: "MultiAssetEscrow (CEP-18)",
    contractHash: "8080845bad4f12c4a720dd96551dc64d116208aa71e0ce1410b75afca8e8eb61",
    contractPackageHash: "a3207e9bb29f6cec6c5017e6c7538626f92f001d35cda22585dff9f76a488044",
    deployHash: "836158d90d480df131b8e4cc490ab93f59b672be74f68f151317b36464dce4df",
    version: 2,
    explorer: "https://testnet.cspr.live/contract/8080845bad4f12c4a720dd96551dc64d116208aa71e0ce1410b75afca8e8eb61",
  },
  cep18TestTokenAetusd: {
    key: "cep18_test_token_aetusd",
    name: "CEP-18 test token (AETUSD)",
    contractHash: "177ca5d88f72e1ca72fbe94a24ba34b03830dd1fe63d90d3d719cd6e6d4de754",
    contractPackageHash: "ea6465021cf2c72b672f7a4fbb4039bb84764a800d279e957847bdff8e38f805",
    deployHash: "8e1ef9727f20dcead2af4da5994b0c52c68a0076eeeb15fc50062ce89eff3bda",
    version: 3,
    explorer: "https://testnet.cspr.live/contract/177ca5d88f72e1ca72fbe94a24ba34b03830dd1fe63d90d3d719cd6e6d4de754",
  },
  cep18TestTokenAemat: {
    key: "cep18_test_token_aemat",
    name: "CEP-18 test token (AEMAT)",
    contractHash: "2e319caa09768162144fed4c53f0259ef733ffd97e56a107064026022ac0377b",
    contractPackageHash: "5caa324c3073a8b9fc05076a01e9d4d658cb08a1b4839fa0aa93dac39213e3fd",
    deployHash: "9025fc473f170f2a6d89e5f394bfae170ec5ce899291d3fce1e3af41e4a43045",
    version: 4,
    explorer: "https://testnet.cspr.live/contract/2e319caa09768162144fed4c53f0259ef733ffd97e56a107064026022ac0377b",
  },
  cep78TestTokenAetnft: {
    key: "cep78_test_token_aetnft",
    name: "CEP-78 test NFT (AETNFT)",
    contractHash: "c2dee0f1f40c3dae3f3106f70d69b8768d7426758b43040673f68e271f2bf70a",
    contractPackageHash: "ac38003d1ffe4550aa2ec82cbcd14fc938a078fafc43e111176e7ed6c9a8e85c",
    deployHash: "e3ed5932db63383d1cc7cc3f5ee56648aa28a84c8e401418f502cb6b8ebcb93d",
    version: 1,
    explorer: "https://testnet.cspr.live/contract/c2dee0f1f40c3dae3f3106f70d69b8768d7426758b43040673f68e271f2bf70a",
  },
  casperHtlc: {
    key: "casper_htlc",
    name: "Casper HTLC (bridge Casper leg)",
    contractHash: "5d5a8d79bd37841234cc9c814937609974715fce214ac814e78eb7528ea0a435",
    contractPackageHash: "93f970abd3b13061c0c80986e3c5323ea30b9f2b099f5d12ef785e09b6b2a542",
    deployHash: "2bf2e6732c0c2c2ec833e92cebd07b51f0e4626e33553e9315c0f26e31e854e7",
    version: 1,
    explorer: "https://testnet.cspr.live/contract/5d5a8d79bd37841234cc9c814937609974715fce214ac814e78eb7528ea0a435",
  },
};

export const CONTRACT_COUNT = Object.keys(CONTRACTS).length;
