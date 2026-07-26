import { ExternalLink } from 'lucide-react'
import { CONTRACTS, CONTRACT_COUNT } from '../lib/manifest.generated'

const STATS = [
  { value: String(CONTRACT_COUNT), label: 'Deployed Contracts', sub: 'on Casper Testnet' },
  { value: '369+', label: 'On-Chain Transactions', sub: 'create / release / refund / resolve' },
  { value: '2331', label: 'Automated Tests', sub: '2081 Python + 250 Rust' },
  { value: '140', label: 'API Endpoints', sub: 'OpenAPI-documented' },
  { value: '26', label: 'MCP Tools', sub: 'for LLM tool-calling' },
  { value: '19', label: 'Console Pages', sub: 'all live-wired' },
]

// Hash/URL sourced from the generated manifest (deploy-out/onchain.json) —
// only the marketing label is customized here, so this list can never drift
// from the canonical deployed-contract record.
const truncateHash = (hash: string) => `${hash.slice(0, 8)}…${hash.slice(-4)}`

const EVIDENCE_ORDER: { key: keyof typeof CONTRACTS; label: string }[] = [
  { key: 'escrowManagerV9', label: 'Core Escrow contract (v9)' },
  { key: 'vrfArbiter', label: 'VRF Arbiter contract' },
  { key: 'agentIdentityRegistry', label: 'Agent Identity Registry (v2)' },
  { key: 'multiAssetEscrow', label: 'MultiAssetEscrow (CEP-18)' },
  { key: 'batchEscrowManager', label: 'Escrow Manager (batch)' },
  { key: 'insurancePool', label: 'Insurance Pool' },
  { key: 'cep18TestTokenAemat', label: 'AEMAT (CEP-18 test token)' },
  { key: 'cep18TestTokenAetusd', label: 'AETUSD (CEP-18 test token)' },
  { key: 'cep78TestTokenAetnft', label: 'AETNFT (CEP-78 test NFT)' },
  { key: 'casperHtlc', label: 'Casper HTLC bridge (L85)' },
]

const EVIDENCE = EVIDENCE_ORDER.map(({ key, label }) => {
  const c = CONTRACTS[key]
  return { label, hash: truncateHash(c.contractHash), url: c.explorer }
})

export default function TrustSignals() {
  return (
    <section id="evidence" className="py-20 relative">
      {/* Mascot — right side, thumbs up */}
      <img
        src="/images/mascot/maskot_ok__right.png"
        alt=""
        className="absolute right-0 top-16 w-28 lg:w-36 opacity-40 hover:opacity-70 transition-opacity pointer-events-none hidden lg:block"
        loading="lazy"
      />

      <div className="ae-section">
        <div className="text-center mb-12">
          <div className="text-xs text-ae-accent font-mono tracking-wider mb-3">VERIFIED ON-CHAIN</div>
          <h2 className="text-3xl font-extrabold text-white mb-3">
            Not a Demo — Real Testnet Deployment
          </h2>
          <p className="text-gray-400 text-sm max-w-xl mx-auto">
            Every number below is verifiable on Casper Testnet. No mocks, no simulated data.
          </p>
        </div>

        {/* Stats grid */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-10">
          {STATS.map((s) => (
            <div key={s.label} className="bg-ae-card/50 border border-ae-border/60 rounded-xl p-4 text-center">
              <div className="text-2xl font-black text-white font-mono">{s.value}</div>
              <div className="text-xs text-gray-300 font-semibold mt-1">{s.label}</div>
              <div className="text-[10px] text-gray-600 mt-0.5">{s.sub}</div>
            </div>
          ))}
        </div>

        {/* On-chain evidence links */}
        <div className="bg-ae-card/30 border border-ae-border/40 rounded-xl p-5">
          <div className="text-xs text-gray-500 font-semibold tracking-wide mb-3">VERIFY ON TESTNET</div>
          <div className="grid sm:grid-cols-2 gap-2">
            {EVIDENCE.map((e) => (
              <a
                key={e.hash}
                href={e.url}
                target="_blank"
                rel="noreferrer"
                className="flex items-center justify-between gap-3 px-4 py-2.5 rounded-lg bg-ae-bg/60 border border-ae-border/30 hover:border-ae-accent/30 transition-colors group"
              >
                <div className="min-w-0">
                  <div className="text-xs text-gray-300 font-medium">{e.label}</div>
                  <div className="text-[10px] text-gray-600 font-mono truncate">{e.hash}</div>
                </div>
                <ExternalLink size={12} className="text-gray-600 group-hover:text-ae-accent shrink-0 transition-colors" />
              </a>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
