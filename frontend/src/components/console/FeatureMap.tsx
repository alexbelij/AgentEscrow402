import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import FeatureStatus, { FeatureStatusValue, statusMeta } from './FeatureStatus';

/**
 * Feature Map — a single, read-only inventory of every capability the AE402
 * console exposes, grouped by the same purpose used in the sidebar, with a
 * checkable status pinned to each row.
 *
 * Status assignment rules (self-imposed, so this page stays honest):
 *  - `on-chain` is only claimed when there is a hash in the Contracts page
 *    for the contract that actually powers the capability.
 *  - `live-api` is only claimed when there is a real REST endpoint listed
 *    on the Docs page for that capability.
 *  - `local-demo` is used for capabilities that work in the hosted console
 *    but are not persisted on-chain (e.g. in-memory reputation store).
 *  - `simulation` is used for deterministic simulators/stubs (e.g. the VRF
 *    CSPRNG fallback path when the on-chain VRF is unavailable).
 *  - `planned` is only used for things listed in the repo/roadmap but not
 *    wired into the UI/API — never inline-invented on this page.
 *
 * Every `route` value must resolve to an existing entry in App.tsx; do not
 * add entries here for pages that have not been implemented.
 */
interface FeatureRow {
  name: string;
  value: string;
  route: string;
  status: FeatureStatusValue;
  evidence: string;
}

interface FeatureSection {
  id: string;
  heading: string;
  intro: string;
  rows: FeatureRow[];
}

const SECTIONS: FeatureSection[] = [
  {
    id: 'core-escrow',
    heading: 'Core escrow',
    intro: 'The lifecycle that pays one agent to work for another: lock funds, deliver, release or refund.',
    rows: [
      {
        name: 'Escrow lifecycle',
        value: 'Lock funds, then release or refund based on delivery, with a dispute path if the two agents disagree.',
        route: '/console/escrows',
        status: 'on-chain',
        evidence: 'Core Escrow contract (deployed on testnet, hash on the Contracts page).',
      },
      {
        name: 'Batch escrows',
        value: 'Create, release or cancel up to 50 escrows in one on-chain deploy — the common shape for a coordinator paying a swarm of workers.',
        route: '/console/escrows',
        status: 'on-chain',
        evidence: 'Escrow Manager contract + /escrows/batch* REST endpoints.',
      },
      {
        name: 'Multi-asset escrow (CSPR / CEP-18 / CEP-78)',
        value: 'Escrows that hold native CSPR, a CEP-18 fungible token, or a CEP-78 NFT — pay each worker in the asset they actually want.',
        route: '/console/advanced',
        status: 'on-chain',
        evidence: 'MultiAssetEscrow and the listed test-token contracts are deployed on testnet; see Contracts for the canonical manifest-backed inventory.',
      },
      {
        name: 'Streaming payouts',
        value: 'Escrows that vest linearly between a start and end time, so continuous work gets continuous pay.',
        route: '/console/advanced',
        status: 'live-api',
        evidence: '/escrow/stream and /escrow/{hash}/stream-* endpoints on the hosted API.',
      },
      {
        name: 'Atomic swap (commit-reveal)',
        value: 'A hash-lock primitive so two agents can trade escrows atomically without trusting a middleman with the secret.',
        route: '/console/advanced',
        status: 'live-api',
        evidence: '/escrow/atomic-swap/commit and /reveal endpoints on the hosted API.',
      },
    ],
  },
  {
    id: 'trust-resolution',
    heading: 'Trust & resolution',
    intro: 'What happens when agents disagree, and how the network judges without a human helpdesk.',
    rows: [
      {
        name: 'AI-assisted dispute analysis',
        value: 'Submit evidence, get a reasoned verdict (favor sender / receiver / split / escalate) with a confidence score.',
        route: '/console/arbitration',
        status: 'live-api',
        evidence: '/arbitration/analyze — real LLM call, deterministic heuristic fallback.',
      },
      {
        name: 'VRF arbiter election',
        value: 'Verifiably-random selection of a neutral arbiter from the network — nobody picks a friendly judge.',
        route: '/console/arbitration',
        status: 'on-chain',
        evidence: 'VRF Arbiter contract (deployed on testnet); CSPRNG simulation fallback if unavailable.',
      },
      {
        name: 'CSPRNG fallback arbiter draw',
        value: 'A local fallback draw used when the on-chain VRF is unavailable, so a dispute can still be routed without presenting the result as on-chain randomness.',
        route: '/console/arbitration',
        status: 'simulation',
        evidence: 'Backend falls back to a seeded CSPRNG draw and labels the result accordingly.',
      },
      {
        name: 'Agent Identity Registry',
        value: 'DID-style identity, reputation from real deals, time-based decay, verification levels — a persistent trust signal an agent carries between deals.',
        route: '/console/identity-registry',
        status: 'live-api',
        evidence: 'Live REST API (in-memory store in the hosted sandbox — not persisted on-chain yet).',
      },
      {
        name: 'Agent identity + capabilities',
        value: 'On-chain registration of an agent public key, capabilities and delegation, so counterparties can check who they\'re dealing with before they lock funds.',
        route: '/console/agents',
        status: 'on-chain',
        evidence: 'Agent Identity Registry contract (deployed on testnet).',
      },
      {
        name: 'Evidence bundle',
        value: 'Attach and inspect the evidence a dispute is being decided on — inputs to the arbitration analyzer.',
        route: '/console/evidence',
        status: 'local-demo',
        evidence: 'Hosted console flow; the same payload is what /arbitration/analyze consumes.',
      },
    ],
  },
  {
    id: 'operations',
    heading: 'Operations',
    intro: 'The layer around the escrow lifecycle: who bears the loss, how risky is this deal, what is the network doing right now.',
    rows: [
      {
        name: 'Insurance pool',
        value: 'A shared pool funded by a small per-escrow fee that pays out on covered disputes, so one bad deal doesn\'t sink the coordinator.',
        route: '/console/insurance',
        status: 'on-chain',
        evidence: 'Insurance Pool contract (deployed on testnet); pool accounting managed server-side.',
      },
      {
        name: 'Risk scoring',
        value: 'An anomaly model scores counterparties and jobs so risky deals can be flagged (or repriced by insurance) before funds are locked.',
        route: '/console/risk',
        status: 'live-api',
        evidence: 'Backend risk scorer, computed over the seeded testnet dataset — not a static placeholder.',
      },
      {
        name: 'Console overview',
        value: 'Live health of the hosted API and testnet target: persistence, network mode, deployed contract count, escrow volume.',
        route: '/console/overview',
        status: 'live-api',
        evidence: '/healthz, /stats, /events streamed live from the hosted backend.',
      },
    ],
  },
  {
    id: 'developer-tools',
    heading: 'Developer tools',
    intro: 'Everything a builder needs to wire an agent up to AE402 without reading the whole codebase.',
    rows: [
      {
        name: 'Contract playground',
        value: 'Call escrow contract actions (release / refund / dispute / VRF election) and inspect the raw API response.',
        route: '/console/contracts',
        status: 'live-api',
        evidence: 'Playground calls the hosted API against the deployed testnet contracts.',
      },
      {
        name: 'API sandbox',
        value: 'An interactive explorer for every REST endpoint — pick a call, set parameters, see the live response.',
        route: '/console/sandbox',
        status: 'live-api',
        evidence: 'All calls hit the hosted backend; parameters are user-editable in-page.',
      },
      {
        name: 'Agent demo (x402 walkthrough)',
        value: 'Guided end-to-end run of an x402 agent payment: build the header, create an escrow, release it.',
        route: '/console/agent-demo',
        status: 'live-api',
        evidence: 'Every step is a real request/response against the hosted backend.',
      },
      {
        name: 'API / SDK / MCP documentation',
        value: 'Complete reference for the REST endpoints, the Python SDK with code examples, LangChain integration, and the MCP tool server for AI-agent interop.',
        route: '/console/docs',
        status: 'live-api',
        evidence: 'Docs enumerate the real endpoints and MCP tools shipped with the current backend.',
      },
    ],
  },
  {
    id: 'new-this-round',
    heading: 'New this round',
    intro: 'Capabilities shipped after the Tier-1 baseline — the same claims made on the landing page, with an honest on-chain/API/pending status each.',
    rows: [
      {
        name: 'Casper HTLC bridge',
        value: 'Hash-time-locked atomic swap between the Casper leg and an EVM (Sepolia) leg — same sha256 hashlock on both sides, no custodian in the middle.',
        route: '/console/advanced',
        status: 'on-chain',
        evidence: 'Casper HTLC contract (deployed on testnet, hash on the Contracts page); EVM leg mirrors the same hashlock on Sepolia testnet.',
      },
      {
        name: 'Confidential escrow amounts (ZK)',
        value: 'Opt-in Pedersen commitment + range proof seals the escrow amount behind a blinding factor — every API response redacts it unless you hold the key.',
        route: '/console/sandbox',
        status: 'live-api',
        evidence: '/escrow with confidential: true, plus /escrow/{hash}/reveal on the hosted API.',
      },
      {
        name: 'Compliance & travel-rule engine',
        value: 'Deterministic jurisdiction checks, KYC tiering from the identity registry, and reporting-threshold flags — separate from the permit/reject decision.',
        route: '/console/sandbox',
        status: 'live-api',
        evidence: 'Compliance router on the hosted API; consumes Agent Identity Registry verification levels.',
      },
      {
        name: 'Threshold escrow (Shamir MPC)',
        value: 'Split a release secret into n shares with m-of-n reconstruction — a coalition below the threshold learns nothing, so no single signer can unilaterally release funds.',
        route: '/console/sandbox',
        status: 'live-api',
        evidence: '/threshold/split, /threshold/reconstruct, /threshold/config on the hosted API.',
      },
      {
        name: 'Gaming-reward escrow (Merkle proof)',
        value: 'Operator commits a reward sheet by publishing only its Merkle root; each winner claims independently with an O(log N) inclusion proof — losers\' scores stay private.',
        route: '/console/sandbox',
        status: 'live-api',
        evidence: '/gaming/commit, /gaming/lock, /gaming/proof, /gaming/claim on the hosted API.',
      },
      {
        name: 'Multi-hop A2A choreography',
        value: 'Chain an escrow across N agent hops (A -> B -> C) with a running hash-chain of attestations, so anyone can independently confirm no hop was skipped or reordered.',
        route: '/console/sandbox',
        status: 'live-api',
        evidence: '/intents router (chain_escrow, attest_hop) on the hosted API.',
      },
      {
        name: 'Challenge Arbiter (commit-reveal + bond/slash)',
        value: 'Two-phase VRF-weighted arbiter selection with bonds slashed on no-reveal, a malicious reveal, or losing a ternary arbitration — raises the cost of a corrupt arbiter.',
        route: '/console/overview',
        status: 'planned',
        evidence: 'Code complete + tests green on main (PR #55); not yet deployed to testnet — tracked as pending in TX_MANIFEST.md.',
      },
      {
        name: 'Range Proof Registry',
        value: 'Threshold-attested amount-range proofs using mod-exp on a 3072-bit prime — no ZK-precompile dependency, 3-of-5 attester quorum.',
        route: '/console/overview',
        status: 'planned',
        evidence: 'Code complete + tests green on main (PR #62); not yet deployed to testnet — tracked as pending in TX_MANIFEST.md.',
      },
      {
        name: 'Governance DAO',
        value: 'On-chain voting/quorum/delegation with an AE402-specific action layer (fee changes, arbiter rotation, insurance params, timelock, pause) — 30% quorum, 7-day voting, veto path.',
        route: '/console/overview',
        status: 'planned',
        evidence: 'Code complete + tests green on main (PR #63); not yet deployed to testnet — tracked as pending in TX_MANIFEST.md.',
      },
      {
        name: 'Two-Key Account',
        value: 'Cold/hot key account-abstraction-style account, so a compromised hot key alone can\'t drain funds.',
        route: '/console/overview',
        status: 'planned',
        evidence: 'Code complete + tests green, merged to main 2026-07-24; not yet deployed to testnet — tracked as pending in TX_MANIFEST.md.',
      },
    ],
  },
  {
    id: 'explore',
    heading: 'Explore',
    intro: 'Narrative entry points that walk a non-technical reviewer into the same live console from a use-case angle.',
    rows: [
      {
        name: 'Use cases',
        value: 'Four plain-language scenarios (freelance agent, dispute resolution, reputation over time, agent-swarm payroll) with every step linking straight into the panel that runs it.',
        route: '/console/use-cases',
        status: 'live-api',
        evidence: 'Every step in every scenario links to an existing console route.',
      },
    ],
  },
];

const FeatureMap: React.FC = () => {
  return (
    <div className="space-y-8">
      <section className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-5 text-sm text-gray-300 leading-relaxed">
        <p>
          One inventory of everything the console exposes, grouped by purpose. Each row explains what the capability is
          <em> for</em>, links to the panel that runs it, and pins a strict status so you can tell at a glance whether it is
          backed by a deployed contract, a live REST endpoint, a hosted demo, a simulator, or is only planned.
        </p>
        <div className="mt-4 flex flex-wrap gap-2" role="list" aria-label="Status legend">
          {(['on-chain', 'live-api', 'local-demo', 'simulation', 'planned'] as FeatureStatusValue[]).map((s) => (
            <span key={s} role="listitem" className="inline-flex items-center gap-2 text-xs text-gray-400">
              <FeatureStatus status={s} showTooltip={false} />
              <span className="max-w-[260px]">{statusMeta(s).desc}</span>
            </span>
          ))}
        </div>
      </section>

      {SECTIONS.map((section) => (
        <section key={section.id} aria-labelledby={`fm-${section.id}`} className="space-y-3">
          <div>
            <h2 id={`fm-${section.id}`} className="text-lg font-semibold text-gray-100">{section.heading}</h2>
            <p className="text-sm text-gray-400 mt-0.5">{section.intro}</p>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {section.rows.map((row) => (
              <Link
                key={row.name}
                to={row.route}
                className="group block bg-[#12121a] border border-[#1e1e2e] rounded-lg p-4 hover:border-ae-accent/50 hover:bg-[#151521] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ae-accent-bright"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-gray-100 font-semibold">{row.name}</span>
                      <FeatureStatus status={row.status} />
                    </div>
                    <p className="text-sm text-gray-400 mt-1">{row.value}</p>
                    <p className="text-xs text-gray-500 mt-2"><span className="text-gray-400">Evidence:</span> {row.evidence}</p>
                  </div>
                  <ArrowRight className="w-4 h-4 text-gray-600 group-hover:text-ae-accent-bright shrink-0 mt-1" aria-hidden="true" />
                </div>
                <div className="mt-3 text-xs font-mono text-gray-500 truncate">{row.route}</div>
              </Link>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
};

export default FeatureMap;
