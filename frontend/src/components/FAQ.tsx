import { useState } from 'react'
import { ChevronDown } from 'lucide-react'

const faqs = [
  { q: 'What is the x402 protocol?', a: 'x402 is a payment protocol built on HTTP status 402 (Payment Required). It defines how AI agents negotiate, authorize, and settle payments over standard HTTP requests. AgentEscrow402 implements x402 on Casper Network with escrow protection.' },
  { q: 'How does escrow protect both parties?', a: 'When Agent A requests a service from Agent B, funds are locked in a smart contract. Agent B delivers the service. If the service hash matches, funds are released. If TTL expires without delivery, funds automatically return to Agent A. Neither party can manipulate the outcome.' },
  { q: 'What happens if there\'s a dispute?', a: 'Either party can initiate a dispute by submitting a reason hash. The dispute is recorded on-chain with evidence. In the current version, disputes are resolved by TTL expiry. Future versions will include DAO-based arbitration.' },
  { q: 'How does the reputation system work?', a: 'Every completed escrow increases an agent\'s reputation score. Disputes decrease it. Slashed agents lose both score and staked funds. Reputation is on-chain and publicly queryable — high-reputation agents can access larger escrow limits.' },
  { q: 'Can human users interact with the escrow?', a: 'Yes. While designed for machine-to-machine payments, the dashboard provides a full GUI for creating escrows, monitoring status, and managing disputes. The API and SDK work for both AI agents and human-driven applications.' },
]

export default function FAQ() {
  const [open, setOpen] = useState<number | null>(0)
  return (
    <section id="faq" className="py-24">
      <div className="ae-section">
        <div className="max-w-3xl mx-auto">
          <div className="text-center mb-14">
            <p className="text-xs font-semibold text-purple-400 tracking-widest mb-3">FAQ</p>
            <h2 className="text-3xl font-extrabold text-white">Common questions.</h2>
          </div>
          <div className="space-y-2">
            {faqs.map((f, i) => (
              <div key={i} className="border border-ae-border rounded-xl overflow-hidden bg-ae-card">
                <button onClick={() => setOpen(open === i ? null : i)} className="w-full flex items-center justify-between p-5 text-left hover:bg-white/[0.02] transition-colors">
                  <span className="font-semibold text-white pr-4">{f.q}</span>
                  <ChevronDown className={`w-5 h-5 text-gray-600 shrink-0 transition-transform ${open === i ? 'rotate-180' : ''}`} />
                </button>
                <div className={`overflow-hidden transition-all duration-300 ${open === i ? 'max-h-60' : 'max-h-0'}`}>
                  <p className="px-5 pb-5 text-gray-400 leading-relaxed text-sm">{f.a}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
