import { ExternalLink } from 'lucide-react'

const STATS = [
  { value: '8', label: 'Deployed Contracts', sub: 'on Casper Testnet' },
  { value: '349', label: 'On-Chain Transactions', sub: 'create / release / refund / resolve' },
  { value: '490', label: 'Automated Tests', sub: '450 Python + 40 Rust' },
  { value: '62', label: 'API Endpoints', sub: 'OpenAPI-documented' },
  { value: '26', label: 'MCP Tools', sub: 'for LLM tool-calling' },
  { value: '12', label: 'Console Tabs', sub: 'all live-wired' },
]

const EVIDENCE = [
  {
    label: 'Core Escrow contract (v9)',
    hash: '612cead2…ddd9ec',
    url: 'https://testnet.cspr.live/contract/612cead2226329fafec492042fd96a999df06d1e88c476913a167f44d3ddd9ec',
  },
  {
    label: 'VRF Arbiter contract',
    hash: '78ae2870…9c93',
    url: 'https://testnet.cspr.live/contract/78ae28702deeb2eadec573d95b870f68b928a82a3566e292ff33a9ae2c779c93',
  },
  {
    label: 'Agent Identity Registry (v2)',
    hash: '1f29271d…1cae',
    url: 'https://testnet.cspr.live/contract/1f29271d986818254d42e5551dd8fbb2e2b7f7295bdfcd6558639584ad311cae',
  },
  {
    label: 'MultiAssetEscrow (CEP-18)',
    hash: '52db09a1…d12a',
    url: 'https://testnet.cspr.live/contract/52db09a146158ba2a07b5da07587046985ce8ca3be094fca9ad63cb6b9ecd12a',
  },
]

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
