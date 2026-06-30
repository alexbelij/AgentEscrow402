export default function SDKSection() {
  return (
    <section id="developers" className="py-24 bg-ae-card/30">
      <div className="ae-section">
        <div className="text-center mb-14">
          <p className="text-xs font-semibold text-purple-400 tracking-widest mb-3">DEVELOPERS</p>
          <h2 className="text-3xl font-extrabold text-white mb-4">SDK and MCP server.</h2>
          <p className="text-gray-500 max-w-lg mx-auto">Integrate escrow payments into your AI agent in minutes.</p>
        </div>

        <div className="grid lg:grid-cols-2 gap-6 max-w-5xl mx-auto">
          {/* Python SDK */}
          <div className="bg-ae-card rounded-2xl border border-ae-border overflow-hidden">
            <div className="p-6 border-b border-ae-border">
              <h3 className="text-white font-bold mb-1">Python SDK</h3>
              <p className="text-sm text-gray-500">Full escrow lifecycle — create, release, refund, dispute.</p>
              <div className="mt-3 bg-ae-bg rounded-lg px-4 py-2 font-mono text-xs text-gray-400 inline-block">
                pip install agentescrow402
              </div>
            </div>
            <pre className="p-5 text-xs font-mono text-gray-300 overflow-x-auto leading-relaxed"><code>{`from agentescrow402 import EscrowClient

client = EscrowClient(
    api="https://agentescrow402-api.onrender.com"
)

escrow = client.create(
    receiver="agent-beta",
    amount=50,
    service_hash="0x7f3a...",
    ttl=3600
)
print(escrow.status)  # "LOCKED"`}</code></pre>
          </div>

          {/* MCP */}
          <div className="bg-ae-card rounded-2xl border border-ae-border overflow-hidden">
            <div className="p-6 border-b border-ae-border">
              <h3 className="text-white font-bold mb-1">MCP Server</h3>
              <p className="text-sm text-gray-500">Let any AI agent create and manage escrows via MCP.</p>
              <div className="mt-3 bg-ae-bg rounded-lg px-4 py-2 font-mono text-xs text-gray-400 inline-block">
                uvx agentescrow402-mcp
              </div>
            </div>
            <pre className="p-5 text-xs font-mono text-gray-300 overflow-x-auto leading-relaxed"><code>{`// claude_desktop_config.json
{
  "mcpServers": {
    "agent-escrow-402": {
      "command": "uvx",
      "args": ["agentescrow402-mcp"],
      "env": {
        "ESCROW_API": "https://agentescrow402-api.onrender.com"
      }
    }
  }
}
// Tools: create_escrow, release, refund, dispute, lookup`}</code></pre>
          </div>
        </div>
      </div>
    </section>
  )
}
