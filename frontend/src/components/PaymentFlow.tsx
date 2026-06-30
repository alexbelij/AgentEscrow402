import { Lock, ArrowRight, CheckCircle, RotateCcw, AlertTriangle, Shield } from 'lucide-react'

const STEPS = [
  {
    icon: Lock,
    num: '01',
    title: 'Lock',
    description: 'Agent A locks CSPR in the escrow contract with a service hash and TTL. The X-Payment header is attached to the HTTP request.',
    code: 'POST /escrow\nX-Payment: x402-v1;<hash>;<amount>;<sender>;<ts>;<nonce>;<sig>',
    color: 'text-purple-400',
  },
  {
    icon: ArrowRight,
    num: '02',
    title: 'Deliver',
    description: 'Agent B performs the requested service (inference, data, audit). The escrow stays locked until the sender confirms delivery.',
    code: 'GET /compute?model=gpt4&tokens=4096\n→ {"result": "...", "quality_score": 0.94}',
    color: 'text-cyan-400',
  },
  {
    icon: CheckCircle,
    num: '03',
    title: 'Release',
    description: 'Sender verifies the result and calls release. Funds transfer to the receiver. Both agents gain reputation.',
    code: 'POST /release\n{"service_hash": "5dd33e8e..."}\n→ status: "released", reputation: +5',
    color: 'text-green-400',
  },
]

const SAFEGUARDS = [
  { icon: RotateCcw, label: 'Auto-refund on TTL expiry' },
  { icon: AlertTriangle, label: 'Dispute resolution flow' },
  { icon: Shield, label: '2% insurance pool' },
]

export default function PaymentFlow() {
  return (
    <section id="flow" className="py-24 relative">
      <div className="ae-section">
        <div className="text-center mb-16">
          <h2 className="text-3xl font-extrabold text-white mb-3">
            Three Steps to Secure Payment
          </h2>
          <p className="text-gray-500 text-sm max-w-lg mx-auto">
            Lock → Deliver → Release. If anything goes wrong, safeguards kick in automatically.
          </p>
        </div>

        <div className="grid md:grid-cols-3 gap-6 mb-12">
          {STEPS.map((step) => (
            <div key={step.num} className="relative group">
              <div className="bg-ae-card/60 border border-ae-border rounded-2xl p-6 h-full hover:border-ae-accent/30 transition-colors">
                <div className="flex items-center gap-3 mb-4">
                  <span className={`text-3xl font-black font-mono ${step.color} opacity-40`}>{step.num}</span>
                  <step.icon size={20} className={step.color} />
                  <h3 className="text-white font-bold text-lg">{step.title}</h3>
                </div>
                <p className="text-gray-400 text-sm leading-relaxed mb-4">{step.description}</p>
                <pre className="bg-ae-bg/80 rounded-lg p-3 text-[11px] font-mono text-gray-500 overflow-x-auto leading-relaxed">{step.code}</pre>
              </div>
            </div>
          ))}
        </div>

        <div className="flex flex-wrap justify-center gap-4">
          {SAFEGUARDS.map((s, i) => (
            <div key={i} className="flex items-center gap-2 px-4 py-2 rounded-full bg-ae-card/40 border border-ae-border/50 text-xs text-gray-400">
              <s.icon size={14} className="text-ae-accent" />
              {s.label}
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
