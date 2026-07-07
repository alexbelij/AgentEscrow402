import { useState } from 'react';
import { Book, Code2, Terminal, Server, Shield, Copy, Check, ChevronDown, ChevronRight } from 'lucide-react';

const API_BASE = 'https://ae402.xyz/backend';
const GITHUB_REPO = 'https://github.com/alexbelij/AgentEscrow402';

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000); }}
      className="absolute top-2 right-2 p-1.5 rounded bg-[#1e1e2e] hover:bg-[#2a2a3e] text-gray-400 hover:text-gray-200 transition-colors"
      title="Copy"
    >
      {copied ? <Check className="h-3.5 w-3.5 text-green-400" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}

function CodeBlock({ code, lang = 'python' }: { code: string; lang?: string }) {
  return (
    <div className="relative group rounded-lg overflow-hidden my-3">
      <CopyButton text={code} />
      <pre className="bg-[#0a0a12] border border-[#1e1e2e] p-4 overflow-x-auto text-sm leading-relaxed">
        <code className={`language-${lang} text-gray-300`}>{code}</code>
      </pre>
    </div>
  );
}

function Section({ title, id, icon: Icon, children }: { title: string; id: string; icon: any; children: React.ReactNode }) {
  return (
    <section id={id} className="scroll-mt-20 mb-12">
      <h2 className="text-2xl font-bold text-gray-100 mb-4 flex items-center gap-2 border-b border-[#1e1e2e] pb-3">
        <Icon className="h-6 w-6 text-amber-500" />
        {title}
      </h2>
      {children}
    </section>
  );
}

type EndpointEntry = { method: string; path: string; desc: string; body?: string; response?: string; auth?: boolean };

function EndpointGroup({ name, endpoints }: { name: string; endpoints: EndpointEntry[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border border-[#1e1e2e] rounded-lg mb-3 overflow-hidden">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center justify-between px-4 py-3 bg-[#0e0e16] hover:bg-[#12121a] transition-colors text-left">
        <span className="font-semibold text-gray-200">{name} <span className="text-gray-500 font-normal text-sm ml-2">({endpoints.length} endpoints)</span></span>
        {open ? <ChevronDown className="h-4 w-4 text-gray-500" /> : <ChevronRight className="h-4 w-4 text-gray-500" />}
      </button>
      {open && (
        <div className="divide-y divide-[#1e1e2e]">
          {endpoints.map((ep, i) => (
            <div key={i} className="px-4 py-3 bg-[#08080e]">
              <div className="flex items-center gap-2 mb-1">
                <span className={`text-xs font-mono font-bold px-2 py-0.5 rounded ${
                  ep.method === 'GET' ? 'bg-green-900/40 text-green-400' :
                  ep.method === 'POST' ? 'bg-blue-900/40 text-blue-400' :
                  ep.method === 'PUT' ? 'bg-amber-900/40 text-amber-400' :
                  'bg-red-900/40 text-red-400'
                }`}>{ep.method}</span>
                <code className="text-sm text-gray-300 font-mono">{ep.path}</code>
                {ep.auth && <span title="Requires x402 payment header"><Shield className="h-3.5 w-3.5 text-amber-500" /></span>}
              </div>
              <p className="text-gray-400 text-sm ml-1">{ep.desc}</p>
              {ep.body && <CodeBlock code={ep.body} lang="json" />}
              {ep.response && (
                <div className="mt-2">
                  <p className="text-xs text-gray-500 mb-1">Response:</p>
                  <CodeBlock code={ep.response} lang="json" />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Endpoint data ──────────────────────────────────────────────────────
const ENDPOINT_GROUPS: { name: string; endpoints: EndpointEntry[] }[] = [
  {
    name: 'Core Escrow Lifecycle',
    endpoints: [
      { method: 'POST', path: '/escrow', desc: 'Create a new escrow payment with sender→receiver flow, TTL, and optional insurance.', auth: true,
        body: `{ "receiver": "ab..64hex", "amount": 5000, "service_hash": "64-hex-hash", "ttl": 300 }`,
        response: `{ "service_hash": "...", "deploy_hash": "...", "amount": 5000, "sender": "...", "receiver": "..." }` },
      { method: 'GET', path: '/escrow/{hash}', desc: 'Get escrow details by service_hash: status, amounts, timestamps, dispute info.' },
      { method: 'POST', path: '/release', desc: 'Release funds from a pending escrow to the receiver. Over-cap releases require arbiter quorum.', auth: true,
        body: `{ "service_hash": "64-hex" }` },
      { method: 'POST', path: '/refund', desc: 'Return funds from a pending escrow to the sender.', auth: true,
        body: `{ "service_hash": "64-hex" }` },
      { method: 'POST', path: '/dispute', desc: 'Open a dispute on an active escrow. Triggers arbiter election.', auth: true,
        body: `{ "service_hash": "64-hex", "reason_hash": "sha256-of-reason" }` },
      { method: 'POST', path: '/resolve', desc: 'Resolve a disputed escrow with arbiter signatures. Funds go to winner.', auth: true,
        body: `{ "service_hash": "64-hex", "in_favor_of": "sender|receiver", "arbiter_pubkeys": [...], "arbiter_signatures": [...] }` },
      { method: 'GET', path: '/escrows', desc: 'List escrows with pagination and optional status filter.', response: `{ "escrows": [...], "total": 42, "offset": 0, "limit": 10 }` },
      { method: 'GET', path: '/escrow/{hash}/history', desc: 'Get full state-change history of an escrow.' },
      { method: 'GET', path: '/estimate', desc: 'Estimate fees for a given escrow amount. Query: ?amount=5000', response: `{ "amount": 5000, "net_amount": 4900.0, "insurance_fee": 100.0, "fee_bps": 200 }` },
      { method: 'POST', path: '/compute-hash', desc: 'Compute deterministic service_hash. Query: ?sender=...&receiver=...&amount=...&nonce=...' },
    ],
  },
  {
    name: 'Batch Operations (up to 50 escrows per deploy)',
    endpoints: [
      { method: 'POST', path: '/escrows/batch', desc: 'Create up to 50 escrows in one on-chain deploy via batch-funder WASM.', auth: true,
        body: `{ "escrows": [{ "receiver": "...", "amount": 5000, "service_hash": "...", "ttl": 300 }, ...] }` },
      { method: 'POST', path: '/escrows/batch-release', desc: 'Release multiple escrows atomically. Cap/quorum guard enforced per escrow.', auth: true,
        body: `{ "service_hashes": ["hash1", "hash2"], "arbiter_pubkeys": [], "arbiter_signatures": [] }` },
      { method: 'POST', path: '/escrows/batch-cancel', desc: 'Cancel (refund) multiple pending escrows atomically.', auth: true,
        body: `{ "service_hashes": ["hash1", "hash2"] }` },
    ],
  },
  {
    name: 'Multi-Asset Escrow (CEP-18 tokens, CEP-78 NFTs)',
    endpoints: [
      { method: 'POST', path: '/escrow/multi-asset', desc: 'Create escrow with selectable token type: native CSPR, CEP-18 fungible token, or CEP-78 NFT.', auth: true,
        body: `{ "receiver": "...", "amount": 100, "token": { "type": "cep18", "contract_hash": "..." }, "service_hash": "...", "ttl": 300 }` },
      { method: 'POST', path: '/escrow/multi-asset/{hash}/release', desc: 'Release a multi-asset escrow to the receiver.', auth: true },
      { method: 'POST', path: '/escrow/multi-asset/{hash}/refund', desc: 'Refund a multi-asset escrow to the sender.', auth: true },
      { method: 'POST', path: '/escrow/multi-asset/{hash}/dispute', desc: 'Dispute a multi-asset escrow.', auth: true },
      { method: 'POST', path: '/escrow/multi-asset/{hash}/resolve', desc: 'Resolve a disputed multi-asset escrow.', auth: true },
      { method: 'GET', path: '/escrow/cep18-permit-nonce', desc: 'Get the next CEP-18 permit nonce for gasless token approvals.' },
    ],
  },
  {
    name: 'Streaming Escrow (Linear Vesting)',
    endpoints: [
      { method: 'POST', path: '/escrow/stream', desc: 'Create a streaming escrow: funds vest linearly from start_time to end_time.', auth: true,
        body: `{ "receiver": "...", "amount": 5000, "token": { "type": "native" }, "service_hash": "...", "start_time": 1720000000, "end_time": 1720003600 }` },
      { method: 'GET', path: '/escrow/{hash}/stream-status', desc: 'Get streaming escrow vesting progress: elapsed %, claimable amount, time remaining.' },
      { method: 'POST', path: '/escrow/{hash}/stream-claim', desc: 'Claim a fully vested streaming escrow — triggers on-chain release.', auth: true },
    ],
  },
  {
    name: 'HTLC Atomic Swap (Commit-Reveal)',
    endpoints: [
      { method: 'POST', path: '/escrow/atomic-swap/commit', desc: 'Phase 1: sender commits SHA-256(secret) to lock escrow. Only the escrow sender can commit.', auth: true,
        body: `{ "service_hash": "64-hex", "commit_hash": "sha256-of-secret-preimage" }` },
      { method: 'POST', path: '/escrow/atomic-swap/reveal', desc: 'Phase 2: receiver reveals preimage. If sha256(preimage) matches commit, funds release.', auth: true,
        body: `{ "service_hash": "64-hex", "preimage": "secret-string" }` },
    ],
  },
  {
    name: 'Insurance Pool',
    endpoints: [
      { method: 'GET', path: '/insurance/pool-stats', desc: 'Get insurance pool balance, total deposited, claims paid, active policies.' },
      { method: 'GET', path: '/insurance/premium-quote', desc: 'Calculate premium. Query: ?escrow_amount=...&agent_id=...&service_type=general' },
      { method: 'POST', path: '/insurance/deposit', desc: 'Deposit funds into the insurance pool to earn rewards.', auth: true },
      { method: 'POST', path: '/insurance/claim', desc: 'File an insurance claim for a disputed/failed escrow.', auth: true },
    ],
  },
  {
    name: 'AI Arbitration',
    endpoints: [
      { method: 'POST', path: '/arbitration/analyze', desc: 'Submit a dispute for AI-assisted analysis. Uses multi-provider LLM (Groq/Nvidia/OpenRouter) with fallback.', auth: true },
      { method: 'GET', path: '/arbitration/history', desc: 'Get past AI arbitration results.' },
    ],
  },
  {
    name: 'VRF Arbiter Election',
    endpoints: [
      { method: 'POST', path: '/vrf/elect', desc: 'Elect an arbiter through on-chain VRF (or cryptographic CSPRNG fallback). Verifiable, unbiased selection.', auth: true,
        body: `{ "dispute_id": "...", "sender": "...", "receiver": "...", "seed_hash": "64-hex" }` },
      { method: 'GET', path: '/vrf/election/{dispute_id}', desc: 'Look up a past VRF election result by dispute ID.' },
      { method: 'GET', path: '/vrf/arbiters', desc: 'List all registered arbiter public keys.' },
      { method: 'POST', path: '/vrf/arbiters/register', desc: 'Register a new arbiter public key for VRF elections.' },
    ],
  },
  {
    name: 'Agent Identity (DID)',
    endpoints: [
      { method: 'POST', path: '/identity/register', desc: 'Register a new DID-style agent identity with public key and DID document hash.', auth: true },
      { method: 'GET', path: '/identity/{agent_id}', desc: 'Look up an agent identity, capabilities, and reputation.' },
      { method: 'POST', path: '/identity/delegate', desc: 'Delegate identity authority to another key.', auth: true },
      { method: 'GET', path: '/identity/capabilities/{agent_id}', desc: 'List agent capabilities (compute, data, arbitration, etc.).' },
    ],
  },
  {
    name: 'On-Chain Identity Registry',
    endpoints: [
      { method: 'POST', path: '/identity-registry/register', desc: 'Register agent with on-chain DID, capabilities, and metadata.', auth: true },
      { method: 'GET', path: '/identity-registry/{did}', desc: 'Get agent registration details by DID.' },
      { method: 'GET', path: '/identity-registry/by-account/{hash}', desc: 'Look up agent by Casper account hash.' },
      { method: 'GET', path: '/identity-registry/{did}/reputation', desc: 'Get on-chain reputation score for an agent.' },
      { method: 'POST', path: '/identity-registry/{did}/decay', desc: 'Apply time-based reputation decay.' },
      { method: 'POST', path: '/identity-registry/{did}/slash', desc: 'Slash reputation for bad behavior.' },
      { method: 'POST', path: '/identity-registry/{did}/verify', desc: 'Verify agent identity with attestation.' },
      { method: 'PUT', path: '/identity-registry/{did}/capabilities', desc: 'Update agent capabilities.' },
      { method: 'GET', path: '/identity-registry/search/agents', desc: 'Search agents by capabilities, reputation, or status.' },
      { method: 'GET', path: '/identity-registry/stats/summary', desc: 'Get registry-wide statistics: total agents, avg reputation, capability distribution.' },
    ],
  },
  {
    name: 'Risk Scoring (IsolationForest ML)',
    endpoints: [
      { method: 'GET', path: '/risk/score/{agent}', desc: 'Compute anomaly-detection risk score for one agent using IsolationForest features.' },
      { method: 'GET', path: '/risk/dashboard', desc: 'Aggregated risk scores for all known agents.' },
    ],
  },
  {
    name: 'Reputation & Agents',
    endpoints: [
      { method: 'GET', path: '/reputation/{agent}', desc: 'Get reputation score, success rate, dispute history for an agent.' },
      { method: 'GET', path: '/agents', desc: 'List all registered agents with reputation scores.' },
    ],
  },
  {
    name: 'Admin (deployer key required)',
    endpoints: [
      { method: 'POST', path: '/admin/configure-fee', desc: 'Set insurance fee basis points (e.g. 200 = 2%).' },
      { method: 'POST', path: '/admin/set-release-cap', desc: 'Set the release cap threshold requiring arbiter quorum.' },
      { method: 'POST', path: '/admin/set-arbiters', desc: 'Configure arbiter public keys and quorum threshold.' },
      { method: 'POST', path: '/admin/emergency-freeze', desc: 'Freeze all escrow operations (emergency circuit breaker).' },
      { method: 'POST', path: '/admin/unfreeze', desc: 'Resume operations after freeze.' },
    ],
  },
  {
    name: 'System',
    endpoints: [
      { method: 'GET', path: '/health', desc: 'Health check: API status, database, contract hash, sandbox mode.' },
      { method: 'GET', path: '/stats', desc: 'Aggregate protocol stats: total escrows, volume, success rate.' },
      { method: 'GET', path: '/contracts', desc: 'List all deployed smart contracts with on-chain hashes and explorer links.' },
      { method: 'GET', path: '/events', desc: 'Server-Sent Events (SSE) stream for real-time escrow lifecycle events.' },
      { method: 'GET', path: '/wasm/escrow_funder', desc: 'Download the escrow_funder.wasm session code for client-side deploys.' },
    ],
  },
];

const MCP_TOOLS = [
  { group: 'Escrow Lifecycle', tools: [
    { name: 'create_escrow', desc: 'Lock funds between sender and receiver with optional TTL', args: 'receiver, amount, service_hash, ttl' },
    { name: 'release_escrow', desc: 'Release funds to receiver', args: 'service_hash' },
    { name: 'refund_escrow', desc: 'Return funds to sender', args: 'service_hash' },
    { name: 'dispute_escrow', desc: 'Open a dispute on active escrow', args: 'service_hash, reason_hash' },
    { name: 'get_escrow', desc: 'Fetch current status and details', args: 'service_hash' },
    { name: 'list_escrows', desc: 'List all escrows with optional filter', args: 'status?, limit?, offset?' },
    { name: 'get_escrow_history', desc: 'Full state-change history', args: 'service_hash' },
    { name: 'build_x402_header', desc: 'Build an x402 payment header', args: 'escrow_hash, amount, sender' },
    { name: 'compute_hash', desc: 'Compute deterministic service_hash', args: 'sender, receiver, amount, nonce' },
    { name: 'estimate_fee', desc: 'Estimate fees and insurance cost', args: 'amount' },
  ]},
  { group: 'Reputation & Stats', tools: [
    { name: 'get_reputation', desc: 'Query on-chain reputation score', args: 'agent' },
    { name: 'list_agents', desc: 'List all known agents with scores', args: '' },
    { name: 'get_stats', desc: 'Aggregate escrow statistics', args: '' },
    { name: 'get_events', desc: 'Get recent escrow events', args: '' },
    { name: 'health_check', desc: 'Check API and blockchain health', args: '' },
  ]},
  { group: 'AI Arbitration', tools: [
    { name: 'submit_dispute_arbitration', desc: 'Submit dispute for AI-assisted arbitration', args: 'dispute_id, evidence' },
    { name: 'get_arbitration_result', desc: 'Get AI verdict and reasoning', args: 'dispute_id' },
    { name: 'appeal_arbitration', desc: 'Appeal an AI arbitration decision', args: 'dispute_id, reason' },
  ]},
  { group: 'Risk Scoring', tools: [
    { name: 'calculate_risk_score', desc: 'IsolationForest anomaly-detection score', args: 'agent' },
    { name: 'get_risk_dashboard', desc: 'Aggregated risk scores for all agents', args: '' },
  ]},
  { group: 'Identity Registry', tools: [
    { name: 'register_identity', desc: 'Register new agent identity with DID', args: 'agent_id, public_key, capabilities' },
    { name: 'get_identity', desc: 'Look up agent identity and reputation', args: 'agent_id' },
  ]},
  { group: 'VRF, Batch & Streaming', tools: [
    { name: 'elect_arbiter', desc: 'VRF-based on-chain random arbiter election', args: 'dispute_id, sender, receiver, seed_hash' },
    { name: 'batch_release', desc: 'Release multiple escrows atomically', args: 'service_hashes' },
    { name: 'batch_cancel', desc: 'Cancel multiple pending escrows', args: 'service_hashes' },
    { name: 'claim_stream', desc: 'Claim fully-vested streaming escrow', args: 'service_hash' },
  ]},
];

export default function Docs() {
  const [activeTab, setActiveTab] = useState<'api' | 'sdk' | 'mcp'>('api');

  const tabs = [
    { id: 'api' as const, label: 'REST API', icon: Server, count: '62 endpoints' },
    { id: 'sdk' as const, label: 'Python SDK', icon: Code2, count: 'client + LangChain' },
    { id: 'mcp' as const, label: 'MCP Server', icon: Terminal, count: '26 tools' },
  ];

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      {/* Tab switcher */}
      <div className="flex gap-2 border-b border-[#1e1e2e] pb-0">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab.id
                ? 'border-amber-500 text-amber-400'
                : 'border-transparent text-gray-400 hover:text-gray-200'
            }`}
          >
            <tab.icon className="h-4 w-4" />
            {tab.label}
            <span className="text-xs text-gray-500 ml-1">({tab.count})</span>
          </button>
        ))}
      </div>

      {/* API Reference */}
      {activeTab === 'api' && (
        <div className="space-y-8">
          <Section title="REST API Reference" id="api-reference" icon={Server}>
            <div className="bg-[#0e0e16] border border-[#1e1e2e] rounded-lg p-4 mb-6">
              <p className="text-gray-300 mb-2">Base URL: <code className="text-amber-400 bg-[#1a1a24] px-2 py-0.5 rounded">{API_BASE}</code></p>
              <p className="text-gray-400 text-sm">All endpoints return JSON. Authenticated endpoints require an <code className="text-amber-400">X-Payment</code> header with x402 protocol signature (see Authentication below). <a href={`${GITHUB_REPO}/blob/main/docs/openapi.yaml`} target="_blank" rel="noopener" className="text-amber-400 hover:underline">Full OpenAPI spec →</a></p>
            </div>

            <div className="bg-[#0e0e16] border border-amber-500/30 rounded-lg p-4 mb-6">
              <h3 className="text-lg font-semibold text-amber-400 mb-2 flex items-center gap-2">
                <Shield className="h-5 w-5" />
                Authentication: x402 Payment Protocol
              </h3>
              <p className="text-gray-400 text-sm mb-3">
                Endpoints marked with <Shield className="h-3.5 w-3.5 inline text-amber-500" /> require an Ed25519-signed <code>X-Payment</code> header binding the request to the caller&apos;s on-chain identity:
              </p>
              <CodeBlock code={`X-Payment: x402-v1;<escrow_hash>;<amount>;<sender_pubkey>;<timestamp>;<nonce>;<signature>

# signature = Ed25519.sign(private_key, 
#   "x402-v1;<escrow_hash>;<amount>;<sender>;<timestamp>;<nonce>;<METHOD>;<path>"
# )

# The Python SDK handles this automatically:
from sdk.client import EscrowClient
async with EscrowClient.generate("${API_BASE}") as client:
    # All requests are auto-signed with the generated keypair
    escrow = await client.create_escrow(receiver="ab"*32, amount=5000)`} lang="python" />
            </div>

            {ENDPOINT_GROUPS.map((group) => (
              <EndpointGroup key={group.name} name={group.name} endpoints={group.endpoints} />
            ))}

            <div className="bg-[#0e0e16] border border-[#1e1e2e] rounded-lg p-4 mt-6">
              <h3 className="font-semibold text-gray-200 mb-2">Error Responses</h3>
              <p className="text-gray-400 text-sm mb-2">All errors return JSON with a <code className="text-amber-400">detail</code> field:</p>
              <CodeBlock code={`// 400 Bad Request — invalid input
{ "detail": "Invalid service_hash format: must be 64 hex characters" }

// 401 Unauthorized — missing or invalid X-Payment header
{ "detail": "sender identity required" }

// 404 Not Found — escrow doesn't exist
{ "detail": "Escrow not found" }

// 409 Conflict — state conflict (e.g., escrow already released)
{ "detail": "Escrow is not in pending state" }

// 422 Unprocessable Entity — validation error
{ "detail": "Duplicate service_hash in batch request" }`} lang="json" />
            </div>
          </Section>
        </div>
      )}

      {/* SDK */}
      {activeTab === 'sdk' && (
        <div className="space-y-8">
          <Section title="Python SDK" id="sdk" icon={Code2}>
            <p className="text-gray-400 mb-4">Full-featured Python client for the AE402 API. Handles x402 authentication, Ed25519 signing, and all endpoints. <a href={`${GITHUB_REPO}/tree/main/sdk`} target="_blank" rel="noopener" className="text-amber-400 hover:underline">Source code →</a></p>

            <h3 className="text-lg font-semibold text-gray-200 mb-3">Installation</h3>
            <CodeBlock code={`# Clone the repository
git clone ${GITHUB_REPO}.git
cd AgentEscrow402

# Install dependencies
pip install httpx cryptography`} lang="bash" />

            <h3 className="text-lg font-semibold text-gray-200 mb-3 mt-8">Quick Start (Signed Mode — Production)</h3>
            <p className="text-gray-400 text-sm mb-3">The live API requires Ed25519-signed requests. <code>EscrowClient.generate()</code> creates a fresh keypair and signs all requests automatically:</p>
            <CodeBlock code={`from sdk.client import EscrowClient

async with EscrowClient.generate("${API_BASE}") as client:
    # Your agent's on-chain identity (Ed25519 public key, 64 hex chars)
    print(f"Agent identity: {client.sender}")
    
    # Create an escrow: lock 5000 CSPR for a receiver agent
    receiver = "ab" * 32  # real 64-hex Casper account hash
    escrow = await client.create_escrow(
        receiver=receiver,
        amount=5000,
        ttl=300  # expires in 5 minutes
    )
    print(f"Escrow created: {escrow['service_hash']}")
    
    # Check escrow status
    status = await client.get_escrow(escrow["service_hash"])
    print(f"Status: {status['status']}")  # "pending"
    
    # Release funds to receiver (happy path)
    tx = await client.release(escrow["service_hash"], amount=5000)
    print(f"Released: {tx['deploy_hash']}")
    
    # Check reputation after transaction
    rep = await client.get_reputation(client.sender)
    print(f"Reputation: {rep['score']}, success rate: {rep['success_rate']}")`} />

            <h3 className="text-lg font-semibold text-gray-200 mb-3 mt-8">Persistent Identity (Reuse Keypair)</h3>
            <CodeBlock code={`from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sdk.client import EscrowClient
import json

# Generate once and save
key = Ed25519PrivateKey.generate()
private_bytes = key.private_bytes_raw().hex()
# Save private_bytes to a secure file

# Reuse in subsequent runs
key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_bytes))
client = EscrowClient("${API_BASE}", private_key=key)
# Now client.sender is the same identity every time`} />

            <h3 className="text-lg font-semibold text-gray-200 mb-3 mt-8">Sandbox Mode (Local Development)</h3>
            <CodeBlock code={`# Local server with SANDBOX=true accepts unsigned requests
async with EscrowClient("http://localhost:8000", sender="agent-001", sandbox=True) as client:
    escrow = await client.create_escrow(receiver="ab"*32, amount=5000, ttl=300)
    await client.release(escrow["service_hash"])`} />

            <h3 className="text-lg font-semibold text-gray-200 mb-3 mt-8">Full Dispute Lifecycle</h3>
            <CodeBlock code={`from sdk.client import EscrowClient
import hashlib

async with EscrowClient.generate("${API_BASE}") as sender_client:
    # Sender creates escrow
    escrow = await sender_client.create_escrow(
        receiver="ab"*32, amount=10000, ttl=600
    )
    
    # Sender disputes (service quality issue)
    reason = "AI model returned incorrect results"
    reason_hash = hashlib.sha256(reason.encode()).hexdigest()
    await sender_client.dispute(
        escrow["service_hash"],
        reason_hash=reason_hash
    )
    
    # Check dispute status
    disputed = await sender_client.get_escrow(escrow["service_hash"])
    print(f"Status: {disputed['status']}")  # "disputed"
    
    # AI arbitration analyzes the dispute
    analysis = await sender_client.arbitration_analyze(
        escrow["service_hash"],
        evidence={"reason": reason, "logs": "..."}
    )
    print(f"AI verdict: {analysis['verdict']}")
    print(f"Confidence: {analysis['confidence']}")
    print(f"Reasoning: {analysis['reasoning']}")`} />

            <h3 className="text-lg font-semibold text-gray-200 mb-3 mt-8">Available Client Methods</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="border-b border-[#1e1e2e]">
                    <th className="text-left py-2 px-3 text-gray-400 font-medium">Method</th>
                    <th className="text-left py-2 px-3 text-gray-400 font-medium">Description</th>
                  </tr>
                </thead>
                <tbody className="text-gray-300">
                  {[
                    ['create_escrow(receiver, amount, ttl)', 'Create and fund a new escrow'],
                    ['get_escrow(hash)', 'Get escrow details by service_hash'],
                    ['release(hash, amount)', 'Release funds to receiver'],
                    ['refund(hash)', 'Refund funds to sender'],
                    ['dispute(hash, reason_hash)', 'Open a dispute'],
                    ['resolve(hash, in_favor_of, pubkeys, sigs)', 'Resolve a dispute'],
                    ['get_escrows(limit, offset, status)', 'List escrows with filtering'],
                    ['get_reputation(agent)', 'Get agent reputation score'],
                    ['get_agents()', 'List all registered agents'],
                    ['get_stats()', 'Get aggregate protocol stats'],
                    ['get_health()', 'Health check'],
                    ['estimate_fee(amount)', 'Estimate fees for escrow amount'],
                    ['arbitration_analyze(hash, evidence)', 'Submit for AI arbitration'],
                    ['build_x402_header(hash, amount)', 'Build signed payment header'],
                  ].map(([method, desc]) => (
                    <tr key={method} className="border-b border-[#1e1e2e]/50">
                      <td className="py-2 px-3 font-mono text-xs text-amber-400">{method}</td>
                      <td className="py-2 px-3">{desc}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>

          <Section title="LangChain Integration" id="langchain" icon={Book}>
            <p className="text-gray-400 mb-4">Use AE402 escrow payments as a LangChain tool — any LLM agent can create, release, and manage escrows. <a href={`${GITHUB_REPO}/blob/main/sdk/langchain_tool.py`} target="_blank" rel="noopener" className="text-amber-400 hover:underline">Source code →</a></p>
            <CodeBlock code={`from sdk.langchain_tool import EscrowPaymentTool
from langchain.agents import initialize_agent, AgentType
from langchain_openai import ChatOpenAI

# Initialize the tool with AE402 backend
tool = EscrowPaymentTool("${API_BASE}", sender="your-agent-identity")

# Use with any LangChain agent
llm = ChatOpenAI(model="gpt-4")
agent = initialize_agent(
    tools=[tool],
    llm=llm,
    agent=AgentType.OPENAI_FUNCTIONS,
)

# The agent can now manage payments autonomously
result = agent.run("Create an escrow of 5000 CSPR for receiver ab...64hex")

# Or use the tool directly
escrow = await tool.run("create", receiver="ab"*32, amount=5000)
release = await tool.run("release", service_hash=escrow["service_hash"])
status = await tool.run("status", service_hash=escrow["service_hash"])`} />
          </Section>
        </div>
      )}

      {/* MCP */}
      {activeTab === 'mcp' && (
        <div className="space-y-8">
          <Section title="MCP Server (Model Context Protocol)" id="mcp" icon={Terminal}>
            <p className="text-gray-400 mb-4">
              The MCP server exposes all 26 AE402 tools to any MCP-compatible LLM (Claude, GPT, Gemini, etc.) — enabling AI agents to autonomously manage escrow payments, disputes, and identity. <a href={`${GITHUB_REPO}/blob/main/sdk/mcp_server.py`} target="_blank" rel="noopener" className="text-amber-400 hover:underline">Source code →</a> · <a href={`${GITHUB_REPO}/blob/main/docs/mcp_tools_schema.json`} target="_blank" rel="noopener" className="text-amber-400 hover:underline">Tools schema →</a>
            </p>

            <h3 className="text-lg font-semibold text-gray-200 mb-3">Start the MCP Server</h3>
            <CodeBlock code={`# Option 1: stdio transport (for Claude Desktop, Cursor, etc.)
python -m sdk.mcp_server

# Option 2: SSE transport (for web clients, remote LLMs)
pip install mcp[sse] uvicorn starlette
python -m sdk.mcp_server --transport sse --port 8402

# Option 3: with custom AE402 backend URL
AE402_API_URL=${API_BASE} python -m sdk.mcp_server`} lang="bash" />

            <h3 className="text-lg font-semibold text-gray-200 mb-3 mt-8">Claude Desktop Configuration</h3>
            <p className="text-gray-400 text-sm mb-3">Add to your <code className="text-amber-400">claude_desktop_config.json</code>:</p>
            <CodeBlock code={`{
  "mcpServers": {
    "ae402-escrow": {
      "command": "python",
      "args": ["-m", "sdk.mcp_server"],
      "cwd": "/path/to/AgentEscrow402",
      "env": {
        "AE402_API_URL": "${API_BASE}"
      }
    }
  }
}`} lang="json" />

            <h3 className="text-lg font-semibold text-gray-200 mb-3 mt-8">Cursor IDE Configuration</h3>
            <p className="text-gray-400 text-sm mb-3">Add to your <code className="text-amber-400">.cursor/mcp.json</code>:</p>
            <CodeBlock code={`{
  "mcpServers": {
    "ae402": {
      "command": "python",
      "args": ["-m", "sdk.mcp_server"],
      "cwd": "/path/to/AgentEscrow402"
    }
  }
}`} lang="json" />

            <h3 className="text-lg font-semibold text-gray-200 mb-3 mt-8">All 26 MCP Tools</h3>
            {MCP_TOOLS.map((group) => (
              <div key={group.group} className="mb-4">
                <h4 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-2">{group.group}</h4>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm border-collapse">
                    <thead>
                      <tr className="border-b border-[#1e1e2e]">
                        <th className="text-left py-2 px-3 text-gray-500 font-medium">Tool</th>
                        <th className="text-left py-2 px-3 text-gray-500 font-medium">Description</th>
                        <th className="text-left py-2 px-3 text-gray-500 font-medium">Arguments</th>
                      </tr>
                    </thead>
                    <tbody className="text-gray-300">
                      {group.tools.map((tool) => (
                        <tr key={tool.name} className="border-b border-[#1e1e2e]/50">
                          <td className="py-2 px-3 font-mono text-xs text-amber-400 whitespace-nowrap">{tool.name}</td>
                          <td className="py-2 px-3">{tool.desc}</td>
                          <td className="py-2 px-3 text-gray-500 text-xs font-mono">{tool.args || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}

            <h3 className="text-lg font-semibold text-gray-200 mb-3 mt-8">Example: AI Agent Managing Payments</h3>
            <CodeBlock code={`# With the MCP server running, an LLM can:

User: "Create an escrow of 10,000 CSPR for agent ab...64hex with 5 min timeout"
AI → calls create_escrow(receiver="ab...", amount=10000, ttl=300)
AI: "Created escrow abc123...! The receiver has 5 minutes to deliver."

User: "The agent delivered, release the payment"
AI → calls release_escrow(service_hash="abc123...")
AI: "Payment released! Deploy hash: def456..."

User: "What's that agent's reputation now?"
AI → calls get_reputation(agent="ab...")
AI: "Score: 95/100, 47 completed escrows, 97.8% success rate"

User: "Something went wrong with escrow xyz789, dispute it"
AI → calls dispute_escrow(service_hash="xyz789", reason_hash="sha256-of-reason")
AI → calls submit_dispute_arbitration(dispute_id="xyz789", evidence={...})
AI: "Dispute opened and submitted for AI arbitration. Verdict: refund recommended (confidence: 0.87)"`} lang="text" />
          </Section>
        </div>
      )}
    </div>
  );
}
