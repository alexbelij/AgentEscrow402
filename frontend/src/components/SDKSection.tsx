export default function SDKSection() {
  return (
    <section id="developers" className="py-24 relative">
      <div className="ae-section">
        <div className="text-center mb-12">
          <h2 className="text-3xl font-extrabold text-white mb-3">
            Developer Tools
          </h2>
          <p className="text-gray-500 text-sm max-w-lg mx-auto">
            Python SDK, LangChain adapter, MCP server — pick your integration path
          </p>
        </div>

        <div className="grid md:grid-cols-3 gap-6">
          {/* SDK */}
          <div className="bg-ae-card/60 border border-ae-border rounded-2xl p-6">
            <div className="text-xs text-ae-accent font-mono mb-3">PYTHON SDK</div>
            <pre className="text-[11px] font-mono text-gray-400 leading-relaxed mb-4 overflow-x-auto">{`from agentescrow402 import EscrowClient

client = EscrowClient(
    base_url="https://...",
    sender="agent-alpha"
)

# Lock funds
escrow = client.create_escrow(
    receiver="agent-beta",
    amount=25000,
    ttl=3600
)

# Release after delivery
client.release(escrow.service_hash)`}</pre>
            <a href="https://github.com/alexbelij/AgentEscrow402/tree/main/sdk" target="_blank" rel="noreferrer" className="text-xs text-ae-accent hover:text-ae-accent-bright">View SDK →</a>
          </div>

          {/* LangChain */}
          <div className="bg-ae-card/60 border border-ae-border rounded-2xl p-6">
            <div className="text-xs text-ae-accent font-mono mb-3">LANGCHAIN TOOL</div>
            <pre className="text-[11px] font-mono text-gray-400 leading-relaxed mb-4 overflow-x-auto">{`from agentescrow402 import (
    EscrowTool
)

tool = EscrowTool(
    base_url="https://..."
)

# Use in your agent chain
agent = initialize_agent(
    tools=[tool],
    llm=ChatOpenAI(),
    agent=AgentType.STRUCTURED
)

agent.run(
    "Pay agent-beta 5000 CSPR"
)`}</pre>
            <a href="https://github.com/alexbelij/AgentEscrow402/tree/main/sdk" target="_blank" rel="noreferrer" className="text-xs text-ae-accent hover:text-ae-accent-bright">View adapter →</a>
          </div>

          {/* MCP */}
          <div className="bg-ae-card/60 border border-ae-border rounded-2xl p-6">
            <div className="text-xs text-ae-accent font-mono mb-3">MCP SERVER</div>
            <pre className="text-[11px] font-mono text-gray-400 leading-relaxed mb-4 overflow-x-auto">{`// stdio transport
{
  "mcpServers": {
    "agentescrow402": {
      "command": "python",
      "args": [
        "-m",
        "agentescrow402.mcp_server"
      ],
      "env": {
        "AE402_URL": "https://..."
      }
    }
  }
}

// Tools exposed:
// - create_escrow
// - release_escrow
// - check_reputation`}</pre>
            <a href="https://github.com/alexbelij/AgentEscrow402/tree/main/sdk" target="_blank" rel="noreferrer" className="text-xs text-ae-accent hover:text-ae-accent-bright">View MCP →</a>
          </div>
        </div>
      </div>
    </section>
  )
}
