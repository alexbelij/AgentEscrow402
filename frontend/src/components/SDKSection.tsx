import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Code2, Bot, Plug } from 'lucide-react'

function Reveal({ children, className }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true)
          observer.disconnect()
        }
      },
      { threshold: 0.15 },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  return (
    <div
      ref={ref}
      className={`${className || ''} transition-all duration-700 ease-out ${
        visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'
      }`}
    >
      {children}
    </div>
  )
}

const TOOLS = [
  {
    icon: Code2,
    tag: 'PYTHON SDK',
    title: 'Drop into any agent runtime in one import',
    description:
      'The Python SDK builds the canonical x402 payload, signs it with your agent\'s Ed25519 key, and talks to the live hosted API — no manual header construction, no raw casper-client calls. Create an escrow, release it on verified delivery, or refund on failure, all in a few lines that read like plain business logic.',
    bullets: [
      'Signs and attaches the X-Payment header automatically',
      'Typed responses for escrow, risk and identity endpoints',
      'Same client the hosted console itself is built on top of',
    ],
    code: `from agentescrow402 import EscrowClient

client = EscrowClient(
    base_url="https://ae402.xyz/backend",
    sender_private_key="ed25519.pem"
)

escrow = client.create_escrow(
    receiver="agent-beta-account-hash",
    amount_motes=25_000_000_000,
    ttl=3600,
    metadata={"service": "market-data"}
)

client.release(escrow.service_hash)`,
    link: 'https://github.com/alexbelij/AgentEscrow402/tree/main/sdk',
    linkLabel: 'View SDK',
  },
  {
    icon: Bot,
    tag: 'AGENT ORCHESTRATION',
    title: 'Gate spend with risk scoring before a single payment moves',
    description:
      'Built for orchestrators that hire other agents on the fly: score a counterparty with the risk model, decide allow/review/deny, and only then lock funds and dispatch the task. This is the same allow/deny logic the console\'s Risk panel uses — reusable as a two-line guard clause in your own agent loop.',
    bullets: [
      'One call to price risk before committing funds',
      'Composable with any LangChain-style tool-calling agent',
      'Escrow + risk + release chained in a single flow',
    ],
    code: `from agentescrow402 import EscrowTool, RiskTool

escrow_tool = EscrowTool(base_url=AE402_URL)
risk_tool = RiskTool(base_url=AE402_URL)

score = risk_tool.score(agent_id)
if score.recommendation != "deny":
    escrow_tool.lock_and_call(
        agent=agent_id,
        task="summarize due diligence pack",
        amount_motes=10_000_000_000,
    )`,
    link: 'https://github.com/alexbelij/AgentEscrow402/tree/main/sdk',
    linkLabel: 'View adapter',
  },
  {
    icon: Plug,
    tag: 'MCP SERVER',
    title: '26 tools your LLM can call directly, zero custom glue code',
    description:
      'Point any MCP-compatible client (Claude, Cursor, your own agent host) at this server and the model gets native tool-calling access to the entire escrow/identity/risk/arbitration surface — creating escrows, checking reputation, electing arbiters and releasing funds — without you writing a single HTTP wrapper.',
    bullets: [
      'Escrow lifecycle, identity registry, risk and VRF arbitration in one server',
      'Same request/response shapes as the live API Sandbox in the console',
      'Works over stdio or SSE — drop-in for any MCP host',
    ],
    code: `{
  "mcpServers": {
    "agentescrow402": {
      "command": "python",
      "args": ["sdk/mcp_server.py"],
      "env": { "AE402_BASE_URL":
        "https://agentescrow402-api.onrender.com" }
    }
  }
}

// 26 tools: create/release/refund/dispute,
// batch_release, batch_cancel, claim_stream,
// elect_arbiter, risk_score, get_identity...`,
    link: 'https://github.com/alexbelij/AgentEscrow402/tree/main/sdk',
    linkLabel: 'View MCP',
  },
]

export default function SDKSection() {
  return (
    <section id="developers" className="py-24 relative">
      <div className="ae-section">
        <div className="text-center mb-16">
          <h2 className="text-3xl font-extrabold text-white mb-3">Developer Tools</h2>
          <p className="text-gray-500 text-sm max-w-2xl mx-auto">
            Three integration paths — Python SDK, LangChain tool, and MCP server with 26 tools.
            The same primitives the live console uses: signed x402 headers, Casper escrow calls,
            risk scoring, identity lookup, and arbitration hooks.
          </p>
        </div>

        <div className="space-y-16">
          {TOOLS.map((tool, i) => {
            const Icon = tool.icon
            const reverse = i % 2 === 1
            return (
              <Reveal key={tool.tag}>
                <div className={`grid lg:grid-cols-2 gap-10 items-center ${reverse ? 'lg:[direction:rtl]' : ''}`}>
                  <div className={reverse ? 'lg:[direction:ltr]' : ''}>
                    <div className="inline-flex items-center gap-2 text-xs text-ae-accent font-mono tracking-wider mb-4">
                      <Icon size={14} />
                      {tool.tag}
                    </div>
                    <h3 className="text-2xl font-bold text-white mb-4 leading-snug">{tool.title}</h3>
                    <p className="text-gray-400 text-sm leading-relaxed mb-5">{tool.description}</p>
                    <ul className="space-y-2 mb-6">
                      {tool.bullets.map((b, bi) => (
                        <li key={bi} className="flex items-start gap-2 text-xs text-gray-400">
                          <span className="text-ae-accent mt-0.5">▸</span>
                          <span>{b}</span>
                        </li>
                      ))}
                    </ul>
                    <a
                      href={tool.link}
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs text-ae-accent hover:text-ae-accent-bright font-semibold"
                    >
                      {tool.linkLabel} →
                    </a>
                  </div>
                  <div className={reverse ? 'lg:[direction:ltr]' : ''}>
                    <div className="bg-ae-card/60 border border-ae-border rounded-2xl p-6 hover:border-ae-accent/30 transition-colors">
                      <pre className="text-[11px] font-mono text-gray-400 leading-relaxed overflow-x-auto">
                        {tool.code}
                      </pre>
                    </div>
                  </div>
                </div>
              </Reveal>
            )
          })}
        </div>
      </div>
    </section>
  )
}
