import { useState } from 'react'
import { ArrowRight, Shield, Zap, Globe, Bot } from 'lucide-react'

const SCENARIOS = [
  {
    icon: Bot,
    title: 'LLM Inference Market',
    agent: 'agent-requester',
    provider: 'agent-gpu-pool',
    amount: 25000,
    ttl: '5 min',
    description: 'An orchestrator agent needs GPT-4-level inference. It locks CSPR in escrow, sends the prompt, and releases payment only after verifying output quality.',
    steps: [
      { label: 'Lock', detail: '25,000 CSPR locked with service hash' },
      { label: 'Compute', detail: 'GPU pool processes 4K token request' },
      { label: 'Verify', detail: 'Requester checks output quality score ≥ 0.85' },
      { label: 'Release', detail: 'Funds released, reputation +5' },
    ],
  },
  {
    icon: Globe,
    title: 'Web Scraping Pipeline',
    agent: 'agent-pipeline',
    provider: 'agent-scraper',
    amount: 8500,
    ttl: '30 min',
    description: 'A data pipeline agent hires a scraper agent to collect structured data from 500 pages. Payment locked until data schema validation passes.',
    steps: [
      { label: 'Lock', detail: '8,500 CSPR escrowed' },
      { label: 'Scrape', detail: '500 pages → structured JSON' },
      { label: 'Validate', detail: 'Schema check: 498/500 valid rows' },
      { label: 'Release', detail: 'Partial release: 98.6% of locked amount' },
    ],
  },
  {
    icon: Shield,
    title: 'Code Audit Service',
    agent: 'agent-developer',
    provider: 'agent-auditor',
    amount: 62000,
    ttl: '2 hrs',
    description: 'A dev agent locks payment before submitting code for security audit. If the auditor finds critical vulnerabilities, the escrow is disputed.',
    steps: [
      { label: 'Lock', detail: '62,000 CSPR locked, TTL 2h' },
      { label: 'Audit', detail: 'Static analysis + fuzz testing' },
      { label: 'Dispute', detail: 'Critical vuln found → escrow disputed' },
      { label: 'Resolve', detail: 'Insurance pool covers 50% refund' },
    ],
  },
  {
    icon: Zap,
    title: 'Real-Time Translation',
    agent: 'agent-chat',
    provider: 'agent-translator',
    amount: 3200,
    ttl: '1 min',
    description: 'A chat agent needs instant translation for a live conversation. Micro-escrow per message batch. Fast TTL ensures no stale locks.',
    steps: [
      { label: 'Lock', detail: '3,200 CSPR per batch' },
      { label: 'Translate', detail: '12 messages EN→JP in 0.8s' },
      { label: 'Deliver', detail: 'Response in X-Payment-Receipt header' },
      { label: 'Auto-release', detail: 'TTL-based auto-release on success' },
    ],
  },
]

export default function Scenarios() {
  const [active, setActive] = useState(0)
  const s = SCENARIOS[active]

  return (
    <section id="scenarios" className="py-24 relative">
      <div className="ae-section">
        <h2 className="text-3xl font-extrabold text-white mb-3 text-center">
          In Practice
        </h2>
        <p className="text-gray-500 text-center mb-12 max-w-lg mx-auto text-sm">
          Illustrative agent-to-agent workflows, each one mapped step-by-step to the real x402 escrow lifecycle
        </p>

        {/* Tabs */}
        <div className="flex flex-wrap justify-center gap-2 mb-10">
          {SCENARIOS.map((sc, i) => {
            const Icon = sc.icon
            return (
              <button
                key={i}
                onClick={() => setActive(i)}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold transition-all ${
                  active === i
                    ? 'bg-ae-accent text-white shadow-lg shadow-purple-600/20'
                    : 'bg-ae-card border border-ae-border text-gray-400 hover:text-white hover:border-gray-600'
                }`}
              >
                <Icon size={14} />
                {sc.title}
              </button>
            )
          })}
        </div>

        {/* Active scenario */}
        <div className="grid lg:grid-cols-2 gap-8">
          {/* Left: description */}
          <div className="bg-ae-card/60 border border-ae-border rounded-2xl p-8">
            <div className="flex items-center gap-3 mb-4">
              <s.icon size={24} className="text-ae-accent" />
              <h3 className="text-xl font-bold text-white">{s.title}</h3>
            </div>
            <p className="text-gray-400 text-sm leading-relaxed mb-6">{s.description}</p>

            <div className="grid grid-cols-3 gap-4">
              <div className="bg-ae-bg/60 rounded-lg p-3 text-center">
                <div className="text-xs text-gray-500 mb-1">Amount</div>
                <div className="text-white font-mono font-bold text-sm">{s.amount.toLocaleString()}</div>
                <div className="text-[10px] text-gray-600">CSPR</div>
              </div>
              <div className="bg-ae-bg/60 rounded-lg p-3 text-center">
                <div className="text-xs text-gray-500 mb-1">TTL</div>
                <div className="text-white font-mono font-bold text-sm">{s.ttl}</div>
              </div>
              <div className="bg-ae-bg/60 rounded-lg p-3 text-center">
                <div className="text-xs text-gray-500 mb-1">Fee</div>
                <div className="text-white font-mono font-bold text-sm">2%</div>
                <div className="text-[10px] text-gray-600">insurance</div>
              </div>
            </div>
          </div>

          {/* Right: step-by-step flow */}
          <div className="space-y-3">
            {s.steps.map((step, i) => (
              <div key={i} className="flex items-start gap-4 group">
                <div className="flex flex-col items-center">
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
                    i === s.steps.length - 1
                      ? 'bg-green-500/20 text-green-400 border border-green-500/30'
                      : 'bg-ae-accent/20 text-ae-accent border border-ae-accent/30'
                  }`}>
                    {i + 1}
                  </div>
                  {i < s.steps.length - 1 && (
                    <div className="w-px h-8 bg-ae-border/60" />
                  )}
                </div>
                <div className="pt-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-white font-semibold text-sm">{step.label}</span>
                    {i < s.steps.length - 1 && <ArrowRight size={12} className="text-gray-600" />}
                  </div>
                  <p className="text-xs text-gray-500">{step.detail}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
