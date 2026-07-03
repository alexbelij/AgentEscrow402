export default function SDKSection() {
  return (
    <section id="developers" className="py-24 relative">
      <div className="ae-section">
        <div className="text-center mb-12">
          <h2 className="text-3xl font-extrabold text-white mb-3">
            Developer Tools
          </h2>
          <p className="text-gray-500 text-sm max-w-2xl mx-auto">
            The same primitives used by the live console: signed x402 intent headers, Casper testnet escrow calls,
            24 MCP tools, SDK helpers, risk scoring and arbitration hooks for agent teams.
          </p>
        </div>

        <div className="grid md:grid-cols-3 gap-6">
          {/* SDK */}
          <div className="bg-ae-card/60 border border-ae-border rounded-2xl p-6">
            <div className="text-xs text-ae-accent font-mono mb-3">PYTHON SDK</div>
            <pre className="text-[11px] font-mono text-gray-400 leading-relaxed mb-4 overflow-x-auto">{`from agentescrow402 import EscrowClient

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

client.release(escrow.service_hash)`}</pre>
            <p className="text-xs text-gray-500 mb-4">Creates the x402 header, signs the canonical payload, and calls the live API.</p>
            <a href="https://github.com/alexbelij/AgentEscrow402/tree/main/sdk" target="_blank" rel="noreferrer" className="text-xs text-ae-accent hover:text-ae-accent-bright">View SDK →</a>
          </div>

          {/* LangChain */}
          <div className="bg-ae-card/60 border border-ae-border rounded-2xl p-6">
            <div className="text-xs text-ae-accent font-mono mb-3">AGENT ORCHESTRATION</div>
            <pre className="text-[11px] font-mono text-gray-400 leading-relaxed mb-4 overflow-x-auto">{`from agentescrow402 import EscrowTool, RiskTool

escrow_tool = EscrowTool(base_url=AE402_URL)
risk_tool = RiskTool(base_url=AE402_URL)

score = risk_tool.score(agent_id)
if score.recommendation != "deny":
    escrow_tool.lock_and_call(
        agent=agent_id,
        task="summarize due diligence pack",
        amount_motes=10_000_000_000,
    )`}</pre>
            <p className="text-xs text-gray-500 mb-4">Use risk scoring before payment and release funds only after verified delivery.</p>
            <a href="https://github.com/alexbelij/AgentEscrow402/tree/main/sdk" target="_blank" rel="noreferrer" className="text-xs text-ae-accent hover:text-ae-accent-bright">View adapter →</a>
          </div>

          {/* MCP */}
          <div className="bg-ae-card/60 border border-ae-border rounded-2xl p-6">
            <div className="text-xs text-ae-accent font-mono mb-3">MCP SERVER</div>
            <pre className="text-[11px] font-mono text-gray-400 leading-relaxed mb-4 overflow-x-auto">{`{
  "mcpServers": {
    "agentescrow402": {
      "command": "python",
      "args": ["-m", "agentescrow402.mcp_server"],
      "env": { "AE402_URL": "https://ae402.xyz/backend" }
    }
  }
}

// 24 tools include:
// create_escrow, release_escrow,
// refund_escrow, dispute_escrow,
// risk_score, vrf_elect,
// mlkem_encrypt_metadata`}</pre>
            <p className="text-xs text-gray-500 mb-4">Judges can inspect the API Sandbox for the exact request/response shapes.</p>
            <a href="https://github.com/alexbelij/AgentEscrow402/tree/main/sdk" target="_blank" rel="noreferrer" className="text-xs text-ae-accent hover:text-ae-accent-bright">View MCP →</a>
          </div>
        </div>
      </div>
    </section>
  )
}
