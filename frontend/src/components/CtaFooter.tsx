export default function CtaFooter() {
  return (
    <section className="py-20">
      <div className="ae-section">
        <div className="relative bg-gradient-to-br from-ae-card to-ae-bg rounded-3xl border border-ae-border p-10 lg:p-14 overflow-hidden">
          <div className="absolute -left-10 -bottom-10 w-64 h-64 rounded-full bg-purple-600/10 blur-[60px] pointer-events-none" />
          <div className="relative z-10 flex flex-col lg:flex-row items-center gap-10">
            <div className="flex-1">
              <h2 className="text-3xl font-extrabold text-white mb-4">Build the payment layer for AI.</h2>
              <p className="text-gray-400 mb-8 max-w-md">Create your first escrow in under a minute. Python SDK, MCP server, and REST API ready to go.</p>
              <div className="flex flex-wrap gap-3">
                <a href="/app" className="inline-flex items-center gap-2 px-8 py-4 bg-ae-accent text-white font-semibold rounded-xl hover:bg-ae-accent-bright transition-all shadow-lg shadow-purple-600/20">Open Dashboard</a>
                <a href="https://github.com/alexbelij/AgentEscrow402" target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 px-8 py-4 border border-ae-border text-gray-300 rounded-xl hover:border-gray-500 transition-colors">View Source</a>
              </div>
            </div>
            <div className="w-40 shrink-0">
              <img src="/images/mascot/maskot_ok.png" alt="" className="w-full animate-rocket-glow" />
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
