export default function X402Protocol() {
  return (
    <section id="x402" className="py-24 relative overflow-hidden">
      <div className="ae-section">
        <div className="grid lg:grid-cols-2 gap-12 items-center">
          {/* Left: explanation */}
          <div>
            <div className="text-xs text-ae-accent font-mono tracking-wider mb-3">HTTP 402 PAYMENT REQUIRED</div>
            <h2 className="text-3xl font-extrabold text-white mb-5">
              The x402 Protocol
            </h2>
            <p className="text-gray-400 text-sm leading-relaxed mb-6">
              HTTP status 402 was reserved for future use since 1999. AgentEscrow402 makes it real — a standard payment header that AI agents attach to every request.
            </p>

            <div className="space-y-4">
              {[
                { label: 'Signature-bound', desc: 'ed25519 signature tied to method + path + nonce. No replay, no forgery.' },
                { label: 'Self-contained', desc: 'Everything needed for payment verification lives in one HTTP header.' },
                { label: 'Framework-agnostic', desc: 'Works with any HTTP client. Python SDK, LangChain, MCP — all supported.' },
              ].map((item, i) => (
                <div key={i} className="flex gap-3">
                  <div className="w-1 bg-ae-accent rounded-full shrink-0" />
                  <div>
                    <div className="text-white font-semibold text-sm">{item.label}</div>
                    <div className="text-gray-500 text-xs">{item.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Right: header visualization */}
          <div className="bg-ae-card/60 border border-ae-border rounded-2xl p-6">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-3 h-3 rounded-full bg-red-500/60" />
              <div className="w-3 h-3 rounded-full bg-yellow-500/60" />
              <div className="w-3 h-3 rounded-full bg-green-500/60" />
              <span className="text-xs text-gray-600 ml-2 font-mono">x402 header anatomy</span>
            </div>
            <pre className="text-[11px] font-mono leading-loose overflow-x-auto">
<span className="text-gray-600">{'// Request with x402 payment'}</span>
{'\n'}<span className="text-purple-400">POST</span> <span className="text-gray-300">/compute</span> <span className="text-gray-600">HTTP/1.1</span>
{'\n'}<span className="text-cyan-400">X-Payment</span><span className="text-gray-500">:</span>
{'\n'}  <span className="text-green-400">x402-v1</span><span className="text-gray-600">;</span>          <span className="text-gray-700">{'// version'}</span>
{'\n'}  <span className="text-yellow-400">5dd33e8e...</span><span className="text-gray-600">;</span>   <span className="text-gray-700">{'// escrow hash'}</span>
{'\n'}  <span className="text-purple-300">25000</span><span className="text-gray-600">;</span>            <span className="text-gray-700">{'// amount (CSPR)'}</span>
{'\n'}  <span className="text-cyan-300">01abc...</span><span className="text-gray-600">;</span>           <span className="text-gray-700">{'// sender pubkey'}</span>
{'\n'}  <span className="text-gray-400">1782837000</span><span className="text-gray-600">;</span>       <span className="text-gray-700">{'// timestamp'}</span>
{'\n'}  <span className="text-gray-400">f7a2b...</span><span className="text-gray-600">;</span>          <span className="text-gray-700">{'// nonce'}</span>
{'\n'}  <span className="text-red-400">ed25519_sig...</span>    <span className="text-gray-700">{'// signature'}</span>
{'\n'}
{'\n'}<span className="text-gray-600">{'// Server response'}</span>
{'\n'}<span className="text-green-400">200</span> <span className="text-gray-500">OK</span>
{'\n'}<span className="text-cyan-400">X-Payment-Receipt</span><span className="text-gray-500">: confirmed</span>
            </pre>
          </div>
        </div>
      </div>
    </section>
  )
}
