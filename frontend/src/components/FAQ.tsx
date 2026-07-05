import { useMemo, useState } from 'react'
import { ChevronDown } from 'lucide-react'

type Category = 'commercial' | 'technical' | 'developer'

const CATEGORY_META: Record<Category, { label: string; cls: string; activeCls: string }> = {
  commercial: {
    label: 'Commercial',
    cls: 'border-purple-500/30 text-purple-300 bg-purple-500/10',
    activeCls: 'border-purple-400 bg-purple-500/20 text-purple-100',
  },
  technical: {
    label: 'Technical',
    cls: 'border-cyan-500/30 text-cyan-300 bg-cyan-500/10',
    activeCls: 'border-cyan-400 bg-cyan-500/20 text-cyan-100',
  },
  developer: {
    label: 'Developer',
    cls: 'border-amber-500/30 text-amber-300 bg-amber-500/10',
    activeCls: 'border-amber-400 bg-amber-500/20 text-amber-100',
  },
}

interface FaqItem {
  q: string
  a: string
  categories: Category[]
}

// Most questions genuinely sit in one lane; a few (marked with two tags)
// answer both a business and a technical reader at once — we tag rather than
// force a single bucket, and let the filter show the union.
const FAQS: FaqItem[] = [
  {
    q: 'What is AgentEscrow402 in one sentence?',
    a: 'A Casper-based payment layer for AI agents: an agent locks funds in escrow, attaches a signed x402 intent to the API request, and releases/refunds/disputes based on delivery evidence.',
    categories: ['commercial', 'technical'],
  },
  {
    q: 'How does the x402 payment flow work?',
    a: 'The request carries an X-Payment header with escrow hash, amount, sender, timestamp, nonce and Ed25519 signature. The API verifies signature shape, replay window and identity before allowing write actions; the hosted console labels its demo identity path separately.',
    categories: ['technical'],
  },
  {
    q: 'Which parts are live on Casper testnet?',
    a: 'The core escrow contract is live for create/release/refund/dispute flows, and three auxiliary contracts are deployed for escrow management, insurance-pool logic and VRF arbiter selection. The console shows deploy hashes/contract hashes where a write hits testnet.',
    categories: ['technical'],
  },
  {
    q: 'What happens if a service provider fails to deliver?',
    a: 'The sender can refund or dispute instead of releasing. Disputes can be analyzed by the LLM arbitration API, escalated to VRF-selected arbiters, and tied to insurance pricing based on risk signals.',
    categories: ['commercial'],
  },
  {
    q: 'How does the risk dashboard help commercially?',
    a: 'It lets a marketplace price escrow/insurance before accepting an agent: Isolation Forest flags abnormal amount/dispute/velocity patterns, then the UI suggests allow/review/deny actions and premium adjustments.',
    categories: ['commercial'],
  },
  {
    q: 'Can I integrate it with existing agent frameworks?',
    a: 'Yes. The repo includes a Python SDK, LangChain-style helpers and an MCP server with 24 tools, so an orchestrator can create escrow, check reputation, elect arbiters and release funds without custom blockchain code.',
    categories: ['developer'],
  },
  {
    q: 'Do I need to write Rust/WASM code to integrate?',
    a: 'No. The Rust/WASM contracts are already written and deployed — you integrate against the REST API, the Python SDK, or the MCP tools. Writing or modifying contract code is only needed if you want to change the on-chain escrow logic itself.',
    categories: ['developer'],
  },
  {
    q: 'Where can I try the API without setting anything up?',
    a: 'The hosted console has a live API Sandbox (pick any endpoint, set parameters, see the real response) and a guided Agent Demo that walks through building a payment header, creating an escrow and releasing it end to end — no local setup or wallet required.',
    categories: ['developer'],
  },
  {
    q: 'What are the fees and business model?',
    a: 'The current demo models a 2% insurance fee on escrow creation. Commercially this becomes transaction take-rate + premium pricing for higher-risk agent jobs + enterprise monitoring/API access.',
    categories: ['commercial'],
  },
  {
    q: 'Is it production audited?',
    a: 'No mainnet-readiness is claimed here. The code has automated tests and security review passes, but formal audit, gas benchmark report and fuzzing are still required before investor/jury submission can be called final.',
    categories: ['technical', 'commercial'],
  },
  {
    q: 'Why not just use a normal payment API or a multisig wallet for this?',
    a: 'Neither gives an autonomous agent a way to prove, on its own and without a human clicking "approve", that a counterparty actually delivered before funds move. AgentEscrow402 replaces that missing trust step with a signed intent + on-chain escrow + dispute path, so two agents that have never interacted before can transact safely without a human in the loop.',
    categories: ['commercial'],
  },
  {
    q: 'What actually breaks without this, in a real agent-to-agent deal?',
    a: 'Pay-first risks the provider never delivering; deliver-first risks the buyer never paying — the classic two-agent trust problem. Escrow removes the "who goes first" risk entirely: funds are locked by a neutral contract before work starts, and only move on verified delivery, TTL expiry (auto-refund) or arbiter resolution.',
    categories: ['commercial'],
  },
  {
    q: 'How does this reduce risk for whoever is paying for agent work?',
    a: 'Three layers stack together: escrow means a bad outcome is refundable/disputable instead of a sunk cost; the risk model flags anomalous counterparties before you ever lock funds; and the insurance pool absorbs part of the loss on a resolved dispute. None of this exists in a plain wallet-to-wallet transfer.',
    categories: ['commercial'],
  },
  {
    q: 'Why Casper specifically, not Ethereum or a payment rail like Stripe?',
    a: 'Stripe requires a human-verified merchant account and card rails that no autonomous agent can hold. Casper gives predictable low fees for high-frequency micro-escrows, upgradeable contracts (so the escrow logic can evolve without breaking existing locked funds), and a WASM contract model that maps cleanly onto typed CEP-18/CEP-78 tokens for multi-asset escrow.',
    categories: ['technical', 'commercial'],
  },
]

const FILTERS: { value: Category | 'all'; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'commercial', label: 'Commercial' },
  { value: 'technical', label: 'Technical' },
  { value: 'developer', label: 'Developer' },
]

export default function FAQ() {
  const [open, setOpen] = useState<number | null>(0)
  const [filter, setFilter] = useState<Category | 'all'>('all')

  const visible = useMemo(
    () => FAQS.map((f, i) => ({ ...f, i })).filter((f) => filter === 'all' || f.categories.includes(filter)),
    [filter],
  )

  return (
    <section id="faq" className="py-24 relative">
      <div className="ae-section max-w-3xl">
        <h2 className="text-3xl font-extrabold text-white mb-3 text-center">Frequently Asked Questions</h2>
        <p className="text-sm text-gray-400 text-center mb-8">
          Filter by what you're evaluating — the business case, the technical design, or how to integrate.
        </p>

        {/* Filter tabs — pill group, active tab uses the same accent color
            as that category's badge so the mapping is instantly visible. */}
        <div className="flex flex-wrap justify-center gap-2 mb-10">
          {FILTERS.map((f) => {
            const isActive = filter === f.value
            const meta = f.value === 'all' ? undefined : CATEGORY_META[f.value]
            return (
              <button
                key={f.value}
                onClick={() => setFilter(f.value)}
                className={`text-xs font-semibold px-4 py-1.5 rounded-full border transition-colors ${
                  f.value === 'all'
                    ? isActive
                      ? 'border-gray-200 bg-white/10 text-white'
                      : 'border-ae-border text-gray-400 hover:text-gray-200'
                    : isActive
                    ? meta!.activeCls
                    : `${meta!.cls} opacity-70 hover:opacity-100`
                }`}
              >
                {f.label}
              </button>
            )
          })}
        </div>

        <div className="space-y-2">
          {visible.map(({ i, q, a, categories }) => (
            <div
              key={i}
              className="border border-ae-border/60 rounded-xl overflow-hidden transition-colors hover:border-ae-border bg-ae-card/30"
            >
              <button
                onClick={() => setOpen(open === i ? null : i)}
                className="w-full flex items-center justify-between gap-4 px-6 py-4 text-left"
              >
                <div className="min-w-0">
                  <span className="text-sm font-semibold text-gray-200 block">{q}</span>
                  <div className="flex gap-1.5 mt-1.5">
                    {categories.map((c) => (
                      <span
                        key={c}
                        className={`text-[10px] font-medium px-1.5 py-0.5 rounded border ${CATEGORY_META[c].cls}`}
                      >
                        {CATEGORY_META[c].label}
                      </span>
                    ))}
                  </div>
                </div>
                <ChevronDown
                  size={18}
                  className={`text-gray-500 shrink-0 transition-transform duration-200 ${open === i ? 'rotate-180' : ''}`}
                />
              </button>
              {open === i && (
                <div className="px-6 pb-5">
                  <p className="text-sm text-gray-400 leading-relaxed">{a}</p>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
