import React, { useState, useCallback } from 'react';
import { api, DEMO_AGENT_RECEIVER, DEMO_AGENT_SENDER } from '../../lib/api';
import {
  FlaskConical,
  Play,
  RefreshCw,
  XCircle,
  CheckCircle,
  Loader2,
  Code,
  Info,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';

// Helper for JSON formatting
const formatJson = (json: any) => {
  try {
    return JSON.stringify(json, null, 2);
  } catch (e) {
    return String(json);
  }
};

// Reusable Textarea Field (from Insurance.tsx)
interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: string;
  id: string;
  error?: string;
}

const Textarea: React.FC<TextareaProps> = ({ label, id, error, ...props }) => (
  <div className="mb-4">
    <label htmlFor={id} className="block text-sm font-medium text-gray-300 mb-1">
      {label}
    </label>
    <textarea
      id={id}
      rows={props.rows || 5}
      className={`w-full p-3 rounded-md bg-gray-800 text-gray-50 border ${
        error ? 'border-red-500' : 'border-[#1e1e2e]'
      } focus:ring-amber-500 focus:border-amber-500 outline-none`}
      {...props}
    />
    {error && <p className="mt-1 text-sm text-red-400">{error}</p>}
  </div>
);

/** A single documented variable: its wire type and what it means, in the
 * same spirit as a generated OpenAPI/Swagger parameter table. */
interface FieldDoc {
  type: string;
  description: string;
  required?: boolean;
}

interface EndpointConfig {
  name: string;
  method: 'GET' | 'POST' | 'PUT' | 'DELETE';
  path: string;
  description: string;
  initialPathParams?: Record<string, string>;
  initialQueryParams?: Record<string, string>;
  initialBody?: object;
  /** Docs for `{param}` placeholders in `path`. */
  pathParamDocs?: Record<string, FieldDoc>;
  /** Docs for query-string parameters. */
  queryParamDocs?: Record<string, FieldDoc>;
  /** Docs for top-level JSON body fields (POST/PUT only). */
  bodyFieldDocs?: Record<string, FieldDoc>;
  apiCall: (
    pathParams: Record<string, string>,
    queryParams: Record<string, string>,
    body: object | undefined
  ) => Promise<any>;
}

const endpoints: EndpointConfig[] = [
  {
    name: 'Get Health',
    method: 'GET',
    path: '/health',
    description: 'Checks the API server health status.',
    apiCall: () => api.getHealth(),
  },
  {
    name: 'Get Stats',
    method: 'GET',
    path: '/stats',
    description: 'Retrieves overall protocol statistics.',
    apiCall: () => api.getStats(),
  },
  {
    name: 'Get Escrows',
    method: 'GET',
    path: '/escrows',
    description: 'Lists escrows with optional filtering and pagination.',
    initialQueryParams: { limit: '10', offset: '0', status: 'pending' },
    queryParamDocs: {
      limit: { type: 'integer', description: 'Max rows to return per page.' },
      offset: { type: 'integer', description: 'Rows to skip, for pagination.' },
      status: { type: 'string enum: pending | released | disputed | refunded | expired', description: 'Filter to a single escrow lifecycle state.' },
    },
    apiCall: (p, q) => api.getEscrows({ limit: Number(q.limit), offset: Number(q.offset), status: q.status as any }),
  },
  {
    name: 'Create Escrow',
    method: 'POST',
    path: '/escrow',
    description: 'Creates a new escrow payment.',
    initialBody: {
      receiver: DEMO_AGENT_RECEIVER,
      amount: 100000000000,
      service_hash: '1111111111111111111111111111111111111111111111111111111111111111',
      ttl: 300,
    },
    bodyFieldDocs: {
      receiver: { type: 'string (hex public key)', description: 'Casper public key of the agent who will receive funds on release.', required: true },
      amount: { type: 'integer (motes)', description: 'Escrow amount in motes (1 CSPR = 1,000,000,000 motes).', required: true },
      service_hash: { type: 'string (64-char hex)', description: 'Unique ID for this escrow; also used to look it up, release, or dispute it.', required: true },
      ttl: { type: 'integer (seconds)', description: 'Time-to-live before the escrow auto-expires and is refundable.', required: false },
    },
    apiCall: (p, q, b) => api.createEscrow(b as any),
  },
  {
    name: 'Get Escrow by Hash',
    method: 'GET',
    path: '/escrow/{hash}',
    description: 'Retrieves details for a specific escrow.',
    initialPathParams: { hash: '1111111111111111111111111111111111111111111111111111111111111111' },
    pathParamDocs: {
      hash: { type: 'string (64-char hex)', description: 'The service_hash returned by / used to create the escrow.', required: true },
    },
    apiCall: (p) => api.getEscrowByHash(p.hash),
  },
  {
    name: 'Release Escrow',
    method: 'POST',
    path: '/release',
    description: 'Releases funds from an escrow.',
    initialBody: {
      service_hash: '1111111111111111111111111111111111111111111111111111111111111111',
    },
    bodyFieldDocs: {
      service_hash: { type: 'string (64-char hex)', description: 'Identifies which pending escrow to release to its receiver.', required: true },
    },
    apiCall: (p, q, b) => api.releaseEscrow(b as any),
  },
  {
    name: 'Get Reputation',
    method: 'GET',
    path: '/reputation/{agent}',
    description: 'Fetches reputation score for an agent.',
    initialPathParams: { agent: DEMO_AGENT_RECEIVER },
    pathParamDocs: {
      agent: { type: 'string (hex public key)', description: 'The agent identity to look up reputation for.', required: true },
    },
    apiCall: (p) => api.getReputation(p.agent),
  },
  {
    name: 'Get Agents',
    method: 'GET',
    path: '/agents',
    description: 'Lists all registered agents.',
    apiCall: () => api.getAgents(),
  },
  {
    name: 'Get Events',
    method: 'GET',
    path: '/events',
    description: 'Explains the live Server-Sent Events stream. /events is an open SSE connection, not a REST list endpoint.',
    apiCall: () => api.getEvents(),
  },
  {
    name: 'Get Insurance Pool Stats',
    method: 'GET',
    path: '/insurance/pool-stats',
    description: 'Retrieves statistics for the insurance pool.',
    apiCall: () => api.getInsurancePoolStats(),
  },
  {
    name: 'Get Premium Quote',
    method: 'GET',
    path: '/insurance/premium-quote',
    description: 'Calculates an insurance premium quote.',
    initialQueryParams: { escrow_amount: '100000000000', agent_id: 'agent-compute-gpt4', service_type: 'general' },
    queryParamDocs: {
      escrow_amount: { type: 'integer (motes)', description: 'Escrow size the premium is calculated against.' },
      agent_id: { type: 'string', description: 'Agent identity the policy would cover.' },
      service_type: { type: 'string', description: 'Risk category used to weight the premium (e.g. general, compute, data).' },
    },
    apiCall: (p, q) => api.getPremiumQuote(Number(q.escrow_amount), q.agent_id, q.service_type),
  },
  {
    name: 'Register Identity',
    method: 'POST',
    path: '/identity/register',
    description: 'Registers a new DID-style agent identity. Shape must include agent_id, public_key and did_document_hash.',
    initialBody: {
      agent_id: 'demo-agent-001',
      public_key: DEMO_AGENT_SENDER,
      did_document_hash: 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
    },
    bodyFieldDocs: {
      agent_id: { type: 'string', description: 'Human-readable unique ID for this agent identity.', required: true },
      public_key: { type: 'string (hex public key)', description: 'Casper public key controlling this identity.', required: true },
      did_document_hash: { type: 'string (64-char hex)', description: 'Hash of the off-chain DID document describing this agent.', required: true },
    },
    apiCall: (p, q, b) => api.registerIdentity(b as any),
  },
  {
    name: 'Risk Dashboard',
    method: 'GET',
    path: '/risk/dashboard',
    description: 'Runs the IsolationForest-backed dashboard over live/demo escrow records.',
    apiCall: () => api.getRiskDashboard(),
  },
  {
    name: 'Risk Score Agent',
    method: 'GET',
    path: '/risk/score/{agent}',
    description: 'Scores one agent with IsolationForest features such as volume, TTL and dispute rate.',
    initialPathParams: { agent: DEMO_AGENT_RECEIVER },
    pathParamDocs: {
      agent: { type: 'string (hex public key)', description: 'The agent identity to compute an anomaly/risk score for.', required: true },
    },
    apiCall: (p) => api.getRiskScore(p.agent),
  },
  {
    name: 'Compute Service Hash',
    method: 'POST',
    path: '/compute-hash',
    description: 'Computes deterministic service_hash from sender, receiver, amount and nonce query parameters.',
    initialQueryParams: { sender: DEMO_AGENT_SENDER, receiver: DEMO_AGENT_RECEIVER, amount: '100000000000', nonce: 'console-demo' },
    queryParamDocs: {
      sender: { type: 'string (hex public key)', description: 'The would-be payer of the escrow.' },
      receiver: { type: 'string (hex public key)', description: 'The would-be payee of the escrow.' },
      amount: { type: 'integer (motes)', description: 'Escrow amount to bind into the hash.' },
      nonce: { type: 'string', description: 'Free-form uniqueness salt so repeat requests do not collide.' },
    },
    apiCall: (p, q) => api.computeServiceHash({ sender: q.sender, receiver: q.receiver, amount: Number(q.amount), nonce: q.nonce }),
  },
  {
    name: 'VRF Arbiter Election',
    method: 'POST',
    path: '/vrf/elect',
    description: 'Elects an arbiter through on-chain VRF when available, otherwise cryptographic local CSPRNG fallback with proof.',
    initialBody: {
      dispute_id: `console-${Date.now()}`,
      sender: DEMO_AGENT_SENDER,
      receiver: DEMO_AGENT_RECEIVER,
      seed_hash: 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
    },
    bodyFieldDocs: {
      dispute_id: { type: 'string', description: 'Identifier of the dispute this election is for.', required: true },
      sender: { type: 'string (hex public key)', description: "The escrow's sender — excluded from the candidate arbiter pool.", required: true },
      receiver: { type: 'string (hex public key)', description: "The escrow's receiver — also excluded from the candidate pool.", required: true },
      seed_hash: { type: 'string (64-char hex)', description: 'Randomness seed fed into the VRF (or CSPRNG fallback) for a verifiable, unbiased pick.', required: true },
    },
    apiCall: (p, q, b) => api.electVrfArbiter(b as any),
  },
];

const Sandbox: React.FC = () => {
  const [selectedName, setSelectedName] = useState(endpoints[0].name);
  const [responses, setResponses] = useState<Record<string, { data: any; error: string | null; loading: boolean }>>({});
  const [pathParams, setPathParams] = useState<Record<string, Record<string, string>>>(
    endpoints.reduce((acc, ep) => ({ ...acc, [ep.name]: ep.initialPathParams || {} }), {})
  );
  const [queryParams, setQueryParams] = useState<Record<string, Record<string, string>>>(
    endpoints.reduce((acc, ep) => ({ ...acc, [ep.name]: ep.initialQueryParams || {} }), {})
  );
  const [requestBodies, setRequestBodies] = useState<Record<string, string>>(
    endpoints.reduce((acc, ep) => ({ ...acc, [ep.name]: ep.initialBody ? formatJson(ep.initialBody) : '' }), {})
  );
  const [newQuery, setNewQuery] = useState({ key: '', value: '' });

  const endpoint = endpoints.find((ep) => ep.name === selectedName) || endpoints[0];
  const response = responses[endpoint.name];

  const handleRun = useCallback(async (endpoint: EndpointConfig) => {
    setResponses((prev) => ({ ...prev, [endpoint.name]: { data: null, error: null, loading: true } }));
    try {
      const currentPathParams = pathParams[endpoint.name] || {};
      const currentQueryParams = queryParams[endpoint.name] || {};
      let currentBody: object | undefined = undefined;
      if (endpoint.method === 'POST' || endpoint.method === 'PUT') {
        try { currentBody = JSON.parse(requestBodies[endpoint.name] || '{}'); }
        catch { throw new Error('Invalid JSON in request body.'); }
      }
      const res = await endpoint.apiCall(currentPathParams, currentQueryParams, currentBody);
      setResponses((prev) => ({
        ...prev,
        [endpoint.name]: res.error
          ? { data: null, error: res.error, loading: false }
          : { data: res.data, error: null, loading: false },
      }));
    } catch (err) {
      setResponses((prev) => ({
        ...prev,
        [endpoint.name]: { data: null, error: err instanceof Error ? err.message : 'An unknown error occurred.', loading: false },
      }));
    }
  }, [pathParams, queryParams, requestBodies]);

  const paramsInPath = endpoint.path.match(/\{(\w+)\}/g) || [];
  const currentQueryParams = queryParams[endpoint.name] || {};

  const addQueryParam = () => {
    const key = newQuery.key.trim();
    if (!key) return;
    setQueryParams((prev) => ({
      ...prev,
      [endpoint.name]: { ...(prev[endpoint.name] || {}), [key]: newQuery.value },
    }));
    setNewQuery({ key: '', value: '' });
  };

  const removeQueryParam = (keyToRemove: string) => {
    setQueryParams((prev) => {
      const next = { ...(prev[endpoint.name] || {}) };
      delete next[keyToRemove];
      return { ...prev, [endpoint.name]: next };
    });
  };

  const methodClass = (method: EndpointConfig['method']) =>
    method === 'GET' ? 'bg-green-600/20 text-green-300 border-green-500/40' :
    method === 'POST' ? 'bg-blue-600/20 text-blue-300 border-blue-500/40' :
    method === 'PUT' ? 'bg-yellow-600/20 text-yellow-300 border-yellow-500/40' :
    'bg-red-600/20 text-red-300 border-red-500/40';

  return (
    <div className="space-y-6">
      <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4 text-sm text-blue-100 leading-relaxed">
        Write operations use the labelled hosted-console <span className="font-mono">X-Payment</span> identity header. This is a live API playground, not screenshots; errors are returned exactly as the backend returns them.
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[360px_minmax(0,1fr)] gap-6 items-start">
        <aside className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-3 xl:sticky xl:top-32">
          <div className="flex items-center gap-2 px-2 pb-3 border-b border-[#1e1e2e] text-gray-300 font-semibold">
            <FlaskConical className="h-5 w-5 text-amber-500" /> Endpoints
          </div>
          <div className="mt-3 max-h-[70vh] overflow-y-auto pr-1 space-y-2">
            {endpoints.map((ep) => (
              <button
                key={ep.name}
                onClick={() => { setSelectedName(ep.name); setNewQuery({ key: '', value: '' }); }}
                className={`w-full text-left rounded-lg border p-3 transition-colors ${selectedName === ep.name ? 'border-amber-500/60 bg-amber-500/10' : 'border-[#1e1e2e] bg-[#0d0d14] hover:border-gray-600'}`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className={`px-2 py-0.5 rounded border text-[11px] font-bold ${methodClass(ep.method)}`}>{ep.method}</span>
                  <span className="text-sm text-gray-50 font-semibold">{ep.name}</span>
                </div>
                <p className="font-mono text-xs text-gray-500 truncate">{ep.path}</p>
              </button>
            ))}
          </div>
        </aside>

        <section className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-6 space-y-5">
          <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-4">
            <div>
              <div className="flex items-center gap-2 mb-2">
                <span className={`px-3 py-1 rounded border text-sm font-bold ${methodClass(endpoint.method)}`}>{endpoint.method}</span>
                <code className="text-amber-300 break-all">{endpoint.path}</code>
              </div>
              <h3 className="text-2xl font-semibold text-gray-50">{endpoint.name}</h3>
              <p className="text-gray-400 mt-2 max-w-3xl">{endpoint.description}</p>
            </div>
            <button
              onClick={() => handleRun(endpoint)}
              className="h-12 inline-flex items-center justify-center px-6 bg-amber-600 hover:bg-amber-700 text-white font-semibold rounded-lg shadow-md disabled:opacity-50"
              disabled={response?.loading}
            >
              {response?.loading ? <Loader2 className="animate-spin h-5 w-5 mr-2" /> : <Play className="h-5 w-5 mr-2" />}
              Run Request
            </button>
          </div>

          {paramsInPath.length > 0 && (
            <div>
              <h4 className="text-md font-semibold text-gray-300 mb-2">Path parameters</h4>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {paramsInPath.map((param) => {
                  const paramName = param.replace(/\{|\}/g, '');
                  const doc = endpoint.pathParamDocs?.[paramName];
                  return (
                    <label key={paramName} className="space-y-1">
                      <span className="text-sm text-gray-400 flex items-center gap-1.5 flex-wrap">
                        <span className="font-mono">{paramName}</span>
                        {doc?.type && <span className="text-[11px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-400 font-mono">{doc.type}</span>}
                        {doc?.required && <span className="text-[11px] text-red-400">required</span>}
                      </span>
                      <input
                        value={pathParams[endpoint.name]?.[paramName] || ''}
                        onChange={(e) => setPathParams((prev) => ({ ...prev, [endpoint.name]: { ...prev[endpoint.name], [paramName]: e.target.value } }))}
                        className="w-full h-11 px-3 rounded-md bg-[#0d0d14] text-gray-50 border border-[#1e1e2e] focus:ring-2 focus:ring-amber-500 outline-none font-mono text-sm"
                      />
                      {doc?.description && <span className="block text-xs text-gray-500">{doc.description}</span>}
                    </label>
                  );
                })}
              </div>
            </div>
          )}

          <div>
            <h4 className="text-md font-semibold text-gray-300 mb-2">Query parameters</h4>
            <div className="space-y-3">
              {Object.keys(currentQueryParams).length === 0 && <p className="text-sm text-gray-500">No query parameters required.</p>}
              {Object.keys(currentQueryParams).map((key) => {
                const doc = endpoint.queryParamDocs?.[key];
                return (
                  <div key={key} className="space-y-1">
                    <div className="grid grid-cols-[160px_minmax(0,1fr)_40px] gap-2">
                      <input value={key} readOnly className="h-10 px-3 rounded-md bg-gray-800 text-gray-300 border border-gray-700 font-mono text-sm" />
                      <input value={currentQueryParams[key]} onChange={(e) => setQueryParams((prev) => ({ ...prev, [endpoint.name]: { ...prev[endpoint.name], [key]: e.target.value } }))} className="h-10 px-3 rounded-md bg-[#0d0d14] text-gray-50 border border-[#1e1e2e] focus:ring-2 focus:ring-amber-500 outline-none" />
                      <button onClick={() => removeQueryParam(key)} className="h-10 inline-flex items-center justify-center text-red-300 hover:text-red-200" title="Remove parameter"><XCircle size={18} /></button>
                    </div>
                    {doc && (
                      <p className="text-xs text-gray-500 pl-1">
                        <span className="font-mono text-gray-400">{doc.type}</span> — {doc.description}
                      </p>
                    )}
                  </div>
                );
              })}
              <div className="grid grid-cols-[160px_minmax(0,1fr)_auto] gap-2 pt-2">
                <input value={newQuery.key} onChange={(e) => setNewQuery((q) => ({ ...q, key: e.target.value }))} placeholder="new_key" className="h-10 px-3 rounded-md bg-[#0d0d14] text-gray-50 border border-[#1e1e2e] focus:ring-2 focus:ring-amber-500 outline-none font-mono text-sm" />
                <input value={newQuery.value} onChange={(e) => setNewQuery((q) => ({ ...q, value: e.target.value }))} placeholder="value" className="h-10 px-3 rounded-md bg-[#0d0d14] text-gray-50 border border-[#1e1e2e] focus:ring-2 focus:ring-amber-500 outline-none" />
                <button onClick={addQueryParam} className="h-10 px-4 rounded-md bg-gray-800 hover:bg-gray-700 text-gray-200 text-sm">Add</button>
              </div>
            </div>
          </div>

          {(endpoint.method === 'POST' || endpoint.method === 'PUT') && (
            <div>
              {endpoint.bodyFieldDocs && (
                <div className="mb-3 rounded-lg border border-[#1e1e2e] overflow-hidden">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="bg-gray-800/60 text-gray-400 text-left">
                        <th className="px-3 py-2 font-semibold">Field</th>
                        <th className="px-3 py-2 font-semibold">Type</th>
                        <th className="px-3 py-2 font-semibold">Description</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(endpoint.bodyFieldDocs).map(([field, doc]) => (
                        <tr key={field} className="border-t border-[#1e1e2e]">
                          <td className="px-3 py-2 font-mono text-gray-200">
                            {field}{doc.required && <span className="text-red-400 ml-1">*</span>}
                          </td>
                          <td className="px-3 py-2 font-mono text-gray-400">{doc.type}</td>
                          <td className="px-3 py-2 text-gray-400">{doc.description}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <Textarea
                label="Request body (JSON)"
                id={`${endpoint.name}-body`}
                value={requestBodies[endpoint.name]}
                onChange={(e) => setRequestBodies((prev) => ({ ...prev, [endpoint.name]: e.target.value }))}
                rows={10}
                placeholder="Enter JSON request body here..."
              />
            </div>
          )}

          <div className="bg-[#0d0d14] border border-[#1e1e2e] rounded-lg p-4">
            <h4 className="text-lg font-semibold text-gray-300 mb-3 flex items-center"><Code className="h-5 w-5 mr-2 text-amber-500" /> Response</h4>
            {response?.loading ? (
              <div className="flex items-center text-amber-400"><Loader2 className="animate-spin h-5 w-5 mr-2" /> Loading…</div>
            ) : response?.error ? (
              <div className="text-red-400 flex items-center"><XCircle className="h-5 w-5 mr-2" /> Error: {response.error}</div>
            ) : response ? (
              <pre className="text-gray-300 text-sm overflow-x-auto max-h-[520px]">{formatJson(response.data)}</pre>
            ) : (
              <p className="text-gray-500 text-sm">Run the selected endpoint to see the response here.</p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
};

export default Sandbox;
