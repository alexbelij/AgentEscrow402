import { ShieldCheck, Zap, Globe, TrendingUp, Lock, Brain } from 'lucide-react'

const REASONS = [
  {
    icon: ShieldCheck,
    title: 'Trustless by Design',
    desc: 'Funds live in a Casper WASM contract, not a hot wallet. Neither party can steal — the contract enforces release conditions, TTL-based refunds, and arbiter quorum.',
    highlight: 'No facilitator, no custodian, no single point of failure.',
  },
  {
    icon: Brain,
    title: 'AI-Native Architecture',
    desc: 'Built for machines that transact without human approval. The x402 header is machine-readable, the SDK signs automatically, and the MCP server gives LLMs direct tool access.',
    highlight: '26 MCP tools your LLM can call natively.',
  },
  {
    icon: Lock,
    title: 'Defense in Depth',
    desc: 'Release cap + arbiter quorum prevents large unilateral withdrawals. Insurance pool absorbs dispute losses. IsolationForest ML risk scoring flags anomalies before funds lock.',
    highlight: 'Three independent safety layers, not one.',
  },
  {
    icon: Globe,
    title: 'Multi-Asset, Multi-Flow',
    desc: 'Not just CSPR — escrow CEP-18 fungible tokens or CEP-78 NFTs through the same lifecycle. HTLC atomic swaps for secret-for-payment exchanges. Streaming for long-running work.',
    highlight: 'One protocol for every agent payment pattern.',
  },
  {
    icon: TrendingUp,
    title: 'Reputation as Infrastructure',
    desc: 'Every completed escrow updates an on-chain trust score with exponential decay. Agents query counterparty reliability before committing funds. Bad actors lose standing automatically.',
    highlight: 'Trust is earned and verifiable, not claimed.',
  },
  {
    icon: Zap,
    title: 'Production-Ready Stack',
    desc: '10 deployed contracts, 140 API endpoints, 2331 tests, 369+ real testnet transactions. Not a demo — a working system with evidence to prove it.',
    highlight: 'Deployed, tested, verified on-chain.',
  },
]

export default function WhyAE402() {
  return (
    <section id="why" className="py-24 relative">
      {/* Subtle background accent */}
      <div className="absolute inset-0 bg-gradient-to-b from-transparent via-purple-900/5 to-transparent pointer-events-none" />

      {/* Mascot — left side, peeking from edge */}
      <img
        src="/images/mascot/maskot_mind__left.png"
        alt=""
        className="absolute left-0 bottom-8 w-28 lg:w-36 opacity-40 hover:opacity-70 transition-opacity pointer-events-none hidden lg:block"
        loading="lazy"
      />

      <div className="ae-section relative">
        <div className="text-center mb-14">
          <div className="text-xs text-ae-accent font-mono tracking-wider mb-3">WHY AGENTESCROW402</div>
          <h2 className="text-3xl font-extrabold text-white mb-4">
            The Missing Trust Layer for Agent Commerce
          </h2>
          <p className="text-gray-400 text-sm max-w-2xl mx-auto leading-relaxed">
            AI agents need to transact autonomously — but without escrow, there's no way to ensure
            delivery before payment or payment before delivery. AgentEscrow402 solves the two-agent
            trust problem with on-chain guarantees.
          </p>
        </div>

        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5">
          {REASONS.map((r) => (
            <div
              key={r.title}
              className="group bg-ae-card/40 border border-ae-border rounded-2xl p-6 hover:border-ae-accent/30 hover:bg-ae-card/60 transition-all"
            >
              <r.icon size={22} className="text-ae-accent mb-4" />
              <h3 className="text-white font-bold text-base mb-2 group-hover:text-ae-accent-bright transition-colors">
                {r.title}
              </h3>
              <p className="text-gray-400 text-sm leading-relaxed mb-3">{r.desc}</p>
              <p className="text-xs text-ae-accent/80 font-medium">{r.highlight}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
