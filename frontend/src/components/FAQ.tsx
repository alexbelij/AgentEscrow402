import { useState } from 'react'
import { ChevronDown } from 'lucide-react'

const FAQS = [
  {
    q: 'How does the x402 payment flow work?',
    a: 'An AI agent sends an HTTP request with an X-Payment header containing a signed escrow reference. The middleware verifies the signature, checks replay protection, and routes the request. Funds stay locked until the service is delivered and confirmed.',
  },
  {
    q: 'What happens if a service provider fails to deliver?',
    a: 'The sender can request a refund before the TTL expires. After TTL, anyone can trigger automatic refund. If there\'s a dispute, the escrow enters "disputed" state for resolution. The insurance pool (2% of each escrow) covers edge cases.',
  },
  {
    q: 'Is the contract audited?',
    a: 'The escrow contract is deployed on Casper testnet with 596 lines of Rust, covering create/release/refund/dispute/resolve entry points. The codebase includes 85+ tests covering all scenarios. Mainnet deployment pending formal audit.',
  },
  {
    q: 'Can I integrate with my existing agent framework?',
    a: 'Yes. The Python SDK provides a single function call to create escrows and attach payment headers. LangChain tool adapter and MCP server are included for direct integration with agent orchestrators.',
  },
  {
    q: 'What are the fees?',
    a: 'A 2% insurance fee is collected on each escrow creation. This funds the insurance pool that covers disputes and failed deliveries. Gas fees for Casper transactions are minimal (~0.01 CSPR per deploy).',
  },
]

export default function FAQ() {
  const [open, setOpen] = useState<number | null>(null)

  return (
    <section id="faq" className="py-24 relative">
      <div className="ae-section max-w-3xl">
        <h2 className="text-3xl font-extrabold text-white mb-12 text-center">
          Common Questions
        </h2>

        <div className="space-y-2">
          {FAQS.map((faq, i) => (
            <div
              key={i}
              className="border border-ae-border/60 rounded-xl overflow-hidden transition-colors hover:border-ae-border"
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
