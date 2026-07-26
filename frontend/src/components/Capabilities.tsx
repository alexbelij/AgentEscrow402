import {
  DollarSign,
  Shield,
  Activity,
  BadgeCheck,
  Gavel,
  Layers,
  Lock,
  Repeat,
  EyeOff,
  ScrollText,
} from 'lucide-react'

const CAPABILITIES = [
  {
    icon: DollarSign,
    title: 'Escrow lifecycle',
    desc: 'Create, release, refund and dispute — the core primitive every other module builds on.',
    href: '/console/escrows',
  },
  {
    icon: Activity,
    title: 'ML risk scoring',
    desc: 'IsolationForest flags anomalous counterparties by amount, dispute rate and velocity before you lock funds.',
    href: '/console/risk',
  },
  {
    icon: Shield,
    title: 'Insurance pool',
    desc: 'A shared pool funded by a small fee on each escrow pays out on covered disputes, priced by risk.',
    href: '/console/insurance',
  },
  {
    icon: BadgeCheck,
    title: 'Agent identity & reputation',
    desc: 'DID-style identities with capability delegation, staking-aware slashing and time-decayed reputation.',
    href: '/console/identity-registry',
  },
  {
    icon: Gavel,
    title: 'VRF + AI arbitration',
    desc: 'Neutral arbiter election via verifiable randomness, plus LLM-assisted dispute-evidence analysis.',
    href: '/console/arbitration',
  },
  {
    icon: Layers,
    title: 'Multi-asset escrow',
    desc: 'CSPR, CEP-18 fungible tokens and CEP-78 NFTs — real on-chain transfers, one escrow, any asset type.',
    href: '/console/advanced',
  },
  {
    icon: Repeat,
    title: 'HTLC atomic swap',
    desc: 'SHA-256 commit/reveal on-chain, so a counterparty other than the sender can unlock funds trustlessly.',
    href: '/console/advanced',
  },
  {
    icon: Lock,
    title: 'ML-KEM metadata privacy',
    desc: 'Post-quantum encryption for escrow metadata, so job details stay private even on a public ledger.',
    href: '/console/escrows',
  },
  {
    icon: EyeOff,
    title: 'Confidential escrow amounts',
    desc: 'Opt-in Pedersen commitment + range proof seals the amount behind a blinding factor — every API response redacts it unless you hold the key.',
    href: '/console/docs',
  },
  {
    icon: ScrollText,
    title: 'Compliance & travel-rule engine',
    desc: 'Deterministic jurisdiction checks, KYC tiering from the identity registry, and reporting-threshold flags — separate from the permit/reject decision.',
    href: '/console/docs',
  },
]

export default function Capabilities() {
  return (
    <section id="capabilities" className="py-24 relative">
      <div className="ae-section">
        <div className="text-center mb-14">
          <h2 className="text-3xl font-extrabold text-white mb-3">The Full Platform</h2>
          <p className="text-gray-500 text-sm max-w-2xl mx-auto">
            Escrow is the entry point — every module below is live in the console today, not a roadmap slide.
          </p>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {CAPABILITIES.map((c) => (
            <a
              key={c.title}
              href={c.href}
              className="group bg-ae-card/60 border border-ae-border rounded-2xl p-5 hover:border-ae-accent/40 hover:bg-ae-card transition-all"
            >
              <c.icon size={20} className="text-ae-accent mb-3" />
              <div className="text-white font-semibold text-sm mb-1.5 group-hover:text-ae-accent-bright transition-colors">
                {c.title}
              </div>
              <p className="text-gray-500 text-xs leading-relaxed">{c.desc}</p>
            </a>
          ))}
        </div>
      </div>
    </section>
  )
}
