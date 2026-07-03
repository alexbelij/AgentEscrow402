import { useState } from 'react'
import { ChevronDown } from 'lucide-react'

const FAQS = [
  {
    q: 'What is AgentEscrow402 in one sentence?',
    a: 'A Casper-based payment layer for AI agents: an agent locks funds in escrow, attaches a signed x402 intent to the API request, and releases/refunds/disputes based on delivery evidence.',
  },
  {
    q: 'How does the x402 payment flow work?',
    a: 'The request carries an X-Payment header with escrow hash, amount, sender, timestamp, nonce and Ed25519 signature. The API verifies signature shape, replay window and identity before allowing write actions; the hosted console labels its demo identity path separately.',
  },
  {
    q: 'Which parts are live on Casper testnet?',
    a: 'The core escrow contract is live for create/release/refund/dispute flows, and three auxiliary contracts are deployed for escrow management, insurance-pool logic and VRF arbiter selection. The console shows deploy hashes/contract hashes where a write hits testnet.',
  },
  {
    q: 'What happens if a service provider fails to deliver?',
    a: 'The sender can refund or dispute instead of releasing. Disputes can be analyzed by the LLM arbitration API, escalated to VRF-selected arbiters, and tied to insurance pricing based on risk signals.',
  },
  {
    q: 'How does the risk dashboard help commercially?',
    a: 'It lets a marketplace price escrow/insurance before accepting an agent: Isolation Forest flags abnormal amount/dispute/velocity patterns, then the UI suggests allow/review/deny actions and premium adjustments.',
  },
  {
    q: 'Can I integrate it with existing agent frameworks?',
    a: 'Yes. The repo includes a Python SDK, LangChain-style helpers and an MCP server with 24 tools, so an orchestrator can create escrow, check reputation, elect arbiters and release funds without custom blockchain code.',
  },
  {
    q: 'What are the fees and business model?',
    a: 'The current demo models a 2% insurance fee on escrow creation. Commercially this becomes transaction take-rate + premium pricing for higher-risk agent jobs + enterprise monitoring/API access.',
  },
  {
    q: 'Is it production audited?',
    a: 'No mainnet-readiness is claimed here. The code has automated tests and security review passes, but formal audit, gas benchmark report and fuzzing are still required before investor/jury submission can be called final.',
  },
]

export default function FAQ() {
  const [open, setOpen] = useState<number | null>(0)

  return (
    <section id="faq" className="py-24 relative">
      <div className="ae-section max-w-3xl">
        <h2 className="text-3xl font-extrabold text-white mb-12 text-center">
          Commercial & Technical FAQ
        </h2>

        <div className="space-y-2">
          {FAQS.map((faq, i) => (
            <div
              key={i}
              className="border border-ae-border/60 rounded-xl overflow-hidden transition-colors hover:border-ae-border bg-ae-card/30"
            >
              <button
                onClick={() => setOpen(open === i ? null : i)}
                className="w-full flex items-center justify-between px-6 py-4 text-left"
              >
                <span className="text-sm font-semibold text-gray-200 pr-4">{faq.q}</span>
                <ChevronDown
                  size={18}
                  className={`text-gray-500 shrink-0 transition-transform duration-200 ${open === i ? 'rotate-180' : ''}`}
                />
              </button>
              {open === i && (
                <div className="px-6 pb-5">
                  <p className="text-sm text-gray-400 leading-relaxed">{faq.a}</p>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
