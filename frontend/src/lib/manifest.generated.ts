// GENERATED FILE -- do not edit by hand.
// Source of truth: deploy-out/onchain.json
// Regenerate with: python3 scripts/generate_frontend_manifest.py
// Verified in CI by tests/test_manifest_frontend_config_sync.py


export const NETWORK = "casper-test";
export const MANIFEST_GENERATED_AT = "2026-07-17T10:00:00Z";
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
    contractHash: "612cead2226329fafec492042fd96a999df06d1e88c476913a167f44d3ddd9ec",
    contractPackageHash: "d3ca33d192dda5ece798db91811ec1259d2197ca0e8d3ea4de043b977d3c8eeb",
    deployHash: "3be113149f35f610116566c3834eb94f1b3a7d0ce0b6834f474747b322ff9094",
    version: 9,
    explorer: "https://testnet.cspr.live/contract/612cead2226329fafec492042fd96a999df06d1e88c476913a167f44d3ddd9ec",
  },
  batchEscrowManager: {
    key: "batch_escrow_manager",
    name: "Escrow Manager",
    contractHash: "bfa8c02cb3ab0f9d7bf03335f324973675200a597162e1e5fa4cb5a77dff675d",
    contractPackageHash: "cdc9924e260bd3a62789a610aae0c351760393b335ebb15a85d89e1df6a3f323",
    deployHash: "704768b711e6831bcd769280678d45326e2835063ccb08fa033b5228fa38db30",
    version: 1,
    explorer: "https://testnet.cspr.live/contract/bfa8c02cb3ab0f9d7bf03335f324973675200a597162e1e5fa4cb5a77dff675d",
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
    contractHash: "1f29271d986818254d42e5551dd8fbb2e2b7f7295bdfcd6558639584ad311cae",
    contractPackageHash: "0b760bb7bf9be5a74ee4ed5626bcc74a8154f221a059e29fc9d768d45fb4a2ba",
    deployHash: "4c8a6e3c0bfa3f6ea9430e3a92b7c44c2b449c1dca5dd5e8f25f74f4506fe586",
    version: 2,
    explorer: "https://testnet.cspr.live/contract/1f29271d986818254d42e5551dd8fbb2e2b7f7295bdfcd6558639584ad311cae",
  },
  multiAssetEscrow: {
    key: "multi_asset_escrow",
    name: "MultiAssetEscrow (CEP-18)",
    contractHash: "52db09a146158ba2a07b5da07587046985ce8ca3be094fca9ad63cb6b9ecd12a",
    contractPackageHash: "a3207e9bb29f6cec6c5017e6c7538626f92f001d35cda22585dff9f76a488044",
    deployHash: "c909bc3dbe093ac3831fe8d5fa8a0e99e1f938ae9f40efaddbb37b67564f3d66",
    version: 1,
    explorer: "https://testnet.cspr.live/contract/52db09a146158ba2a07b5da07587046985ce8ca3be094fca9ad63cb6b9ecd12a",
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
    contractHash: "8ba7df6fd9a12c71de903a915717537eeff4f04adf33f4ed8abf16c254e300a5",
    contractPackageHash: "5caa324c3073a8b9fc05076a01e9d4d658cb08a1b4839fa0aa93dac39213e3fd",
    deployHash: "8a0fb73e124e613c9e65fb5585331ce2196853fb2a98c1493c383e71749051a9",
    version: 3,
    explorer: "https://testnet.cspr.live/contract/8ba7df6fd9a12c71de903a915717537eeff4f04adf33f4ed8abf16c254e300a5",
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
};

export const CONTRACT_COUNT = Object.keys(CONTRACTS).length;
