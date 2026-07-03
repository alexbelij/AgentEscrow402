import React, { useState, useCallback } from 'react';
import { api } from '../../lib/api';
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

interface EndpointConfig {
  name: string;
  method: 'GET' | 'POST' | 'PUT' | 'DELETE';
  path: string;
  description: string;
  initialPathParams?: Record<string, string>;
  initialQueryParams?: Record<string, string>;
  initialBody?: object;
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
    apiCall: (p, q) => api.getEscrows({ limit: Number(q.limit), offset: Number(q.offset), status: q.status as any }),
  },
  {
    name: 'Create Escrow',
    method: 'POST',
    path: '/escrow',
    description: 'Creates a new escrow payment.',
    initialBody: {
      payer: '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
      payee: '01fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210',
      amount: '100',
      token_contract: 'hash-5dd33e8e79789d386832a80c39006002383fa44dd76ba677cae3279f3a134451',
      arbiter: '01abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890',
    },
    apiCall: (p, q, b) => api.createEscrow(b as any),
  },
  {
    name: 'Get Escrow by Hash',
    method: 'GET',
    path: '/escrow/{hash}',
    description: 'Retrieves details for a specific escrow.',
    initialPathParams: { hash: '5dd33e8e79789d386832a80c39006002383fa44dd76ba677cae3279f3a134451' }, // Placeholder
    apiCall: (p) => api.getEscrowByHash(p.hash),
  },
  {
    name: 'Release Escrow',
    method: 'POST',
    path: '/release',
    description: 'Releases funds from an escrow.',
    initialBody: {
      escrow_hash: '5dd33e8e79789d386832a80c39006002383fa44dd76ba677cae3279f3a134451', // Placeholder
      initiator_account: '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
      signature: 'mock_signature_payer_or_arbiter',
    },
    apiCall: (p, q, b) => api.releaseEscrow(b as any),
  },
  {
    name: 'Get Reputation',
    method: 'GET',
    path: '/reputation/{agent}',
    description: 'Fetches reputation score for an agent.',
    initialPathParams: { agent: '01fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210' }, // Placeholder
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
    description: 'Retrieves recent protocol events.',
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
    initialQueryParams: { amount: '100', duration: '2592000' }, // 30 days in seconds
    apiCall: (p, q) => api.getPremiumQuote(Number(q.amount), Number(q.duration)),
  },
  {
    name: 'Register Identity',
    method: 'POST',
    path: '/identity/register',
    description: 'Registers a new agent identity.',
    initialBody: {
      public_key: '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
      name: 'TestAgent_001',
    },
    apiCall: (p, q, b) => api.registerIdentity(b as any),
  },
  // Add more endpoints here following the pattern
];

const Sandbox: React.FC = () => {
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
  const [expandedEndpoints, setExpandedEndpoints] = useState<Record<string, boolean>>({});

  const toggleExpand = (name: string) => {
    setExpandedEndpoints((prev) => ({ ...prev, [name]: !prev[name] }));
  };

  const handleRun = useCallback(async (endpoint: EndpointConfig) => {
    setResponses((prev) => ({ ...prev, [endpoint.name]: { data: null, error: null, loading: true } }));

    try {
      const currentPathParams = pathParams[endpoint.name] || {};
      const currentQueryParams = queryParams[endpoint.name] || {};
      let currentBody: object | undefined = undefined;

      if (endpoint.method === 'POST' || endpoint.method === 'PUT') {
        try {
          currentBody = JSON.parse(requestBodies[endpoint.name] || '{}');
        } catch (e) {
          throw new Error('Invalid JSON in request body.');
        }
      }

      const res = await endpoint.apiCall(currentPathParams, currentQueryParams, currentBody);

      if (res.error) {
        setResponses((prev) => ({
          ...prev,
          [endpoint.name]: { data: null, error: res.error, loading: false },
        }));
      } else {
        setResponses((prev) => ({
          ...prev,
          [endpoint.name]: { data: res.data, error: null, loading: false },
        }));
      }
    } catch (err) {
      setResponses((prev) => ({
        ...prev,
        [endpoint.name]: { data: null, error: err instanceof Error ? err.message : 'An unknown error occurred.', loading: false },
      }));
    }
  }, [pathParams, queryParams, requestBodies]);

  const renderPathParams = (endpoint: EndpointConfig) => {
    const paramsInPath = endpoint.path.match(/\{(\w+)\}/g) || [];
    if (paramsInPath.length === 0) return null;

    return (
      <div className="mb-4">
        <h4 className="text-md font-semibold text-gray-300 mb-2">Path Parameters</h4>
        {paramsInPath.map((param) => {
          const paramName = param.replace(/\{|\}/g, '');
          return (
            <div key={paramName} className="mb-2">
              <label htmlFor={`${endpoint.name}-${paramName}-path`} className="block text-sm font-medium text-gray-400 mb-1">
                {paramName}
              </label>
              <input
                id={`${endpoint.name}-${paramName}-path`}
                type="text"
                value={pathParams[endpoint.name]?.[paramName] || ''}
                onChange={(e) =>
                  setPathParams((prev) => ({
                    ...prev,
                    [endpoint.name]: { ...prev[endpoint.name], [paramName]: e.target.value },
                  }))
                }
                className="w-full p-2 rounded-md bg-gray-700 text-gray-50 border border-gray-600 focus:ring-amber-500 focus:border-amber-500 outline-none"
                placeholder={`Enter ${paramName}`}
              />
            </div>
          );
        })}
      </div>
    );
  };

  const renderQueryParams = (endpoint: EndpointConfig) => {
    const currentQueryParams = queryParams[endpoint.name] || {};
    const queryKeys = Object.keys(currentQueryParams);

    const handleAddQueryParam = () => {
      const newKey = prompt('Enter new query parameter key:');
      if (newKey) {
        setQueryParams((prev) => ({
          ...prev,
          [endpoint.name]: { ...prev[endpoint.name], [newKey]: '' },
        }));
      }
    };

    const handleRemoveQueryParam = (keyToRemove: string) => {
      setQueryParams((prev) => {
        const newParams = { ...prev[endpoint.name] };
        delete newParams[keyToRemove];
        return { ...prev, [endpoint.name]: newParams };
      });
    };

    return (
      <div className="mb-4">
        <h4 className="text-md font-semibold text-gray-300 mb-2">Query Parameters</h4>
        {queryKeys.map((key) => (
          <div key={key} className="flex items-center mb-2 gap-2">
            <input
              type="text"
              value={key}
              readOnly
              className="w-1/3 p-2 rounded-md bg-gray-700 text-gray-50 border border-gray-600 outline-none"
            />
            <input
              type="text"
              value={currentQueryParams[key]}
              onChange={(e) =>
                setQueryParams((prev) => ({
                  ...prev,
                  [endpoint.name]: { ...prev[endpoint.name], [key]: e.target.value },
                }))
              }
              className="w-2/3 p-2 rounded-md bg-gray-700 text-gray-50 border border-gray-600 focus:ring-amber-500 focus:border-amber-500 outline-none"
              placeholder={`Value for ${key}`}
            />
            <button
              onClick={() => handleRemoveQueryParam(key)}
              className="text-red-400 hover:text-red-300 p-1"
              title="Remove parameter"
            >
              <XCircle size={18} />
            </button>
          </div>
        ))}
        <button
          onClick={handleAddQueryParam}
          className="mt-2 px-3 py-1 bg-gray-600 hover:bg-gray-500 text-gray-200 text-sm rounded-md"
        >
          Add Query Param
        </button>
      </div>
    );
  };

  return (
    <div className="space-y-8">
      <h2 className="text-3xl font-bold text-gray-50">API Sandbox</h2>
      <p className="text-gray-400">
        Interact with the AgentEscrow402 API directly. Select an endpoint, fill in parameters/body, and execute the request.
      </p>

      <div className="grid grid-cols-1 gap-6">
        {endpoints.map((endpoint) => (
          <div key={endpoint.name} className="bg-[#12121a] border border-[#1e1e2e] rounded-lg shadow-md p-6">
            <div className="flex justify-between items-center mb-4 cursor-pointer" onClick={() => toggleExpand(endpoint.name)}>
              <h3 className="text-xl font-semibold text-gray-50 flex items-center">
                <span
                  className={`px-3 py-1 rounded-md text-sm font-bold mr-3 ${
                    endpoint.method === 'GET' ? 'bg-green-600' :
                    endpoint.method === 'POST' ? 'bg-blue-600' :
                    endpoint.method === 'PUT' ? 'bg-yellow-600' :
                    'bg-red-600'
                  }`}
                >
                  {endpoint.method}
                </span>
                {endpoint.path.split('/').map((segment, index, arr) => {
                  if (segment.startsWith('{') && segment.endsWith('}')) {
                    const paramName = segment.replace(/\{|\}/g, '');
                    return (
                      <span key={index} className="text-amber-400">
                        /{pathParams[endpoint.name]?.[paramName] || `{${paramName}}`}
                      </span>
                    );
                  }
                  return <span key={index}>{index > 0 ? '/' : ''}{segment}</span>;
                })}
              </h3>
              {expandedEndpoints[endpoint.name] ? <ChevronUp className="h-5 w-5 text-gray-400" /> : <ChevronDown className="h-5 w-5 text-gray-400" />}
            </div>

            {expandedEndpoints[endpoint.name] && (
              <>
                <p className="text-gray-400 mb-4">{endpoint.description}</p>

                {renderPathParams(endpoint)}
                {renderQueryParams(endpoint)}

                {(endpoint.method === 'POST' || endpoint.method === 'PUT') && (
                  <Textarea
                    label="Request Body (JSON)"
                    id={`${endpoint.name}-body`}
                    value={requestBodies[endpoint.name]}
                    onChange={(e) =>
                      setRequestBodies((prev) => ({ ...prev, [endpoint.name]: e.target.value }))
                    }
                    rows={8}
                    placeholder="Enter JSON request body here..."
                  />
                )}

                <div className="flex justify-end gap-3 mt-6">
                  <button
                    onClick={() => handleRun(endpoint)}
                    className="flex items-center px-6 py-3 bg-amber-600 hover:bg-amber-700 text-white font-semibold rounded-lg shadow-md transition-colors duration-200"
                    disabled={responses[endpoint.name]?.loading}
                  >
                    {responses[endpoint.name]?.loading && <Loader2 className="animate-spin h-5 w-5 mr-2" />}
                    Run Request
                  </button>
                </div>

                {responses[endpoint.name] && (
                  <div className="mt-6 p-4 bg-gray-800 rounded-md border border-[#1e1e2e]">
                    <h4 className="text-lg font-semibold text-gray-300 mb-3 flex items-center">
                      <Code className="h-5 w-5 mr-2 text-amber-500" />
                      Response
                    </h4>
                    {responses[endpoint.name]?.loading ? (
                      <div className="flex items-center text-amber-400">
                        <Loader2 className="animate-spin h-5 w-5 mr-2" /> Loading...
                      </div>
                    ) : responses[endpoint.name]?.error ? (
                      <div className="text-red-500 flex items-center">
                        <XCircle className="h-5 w-5 mr-2" /> Error: {responses[endpoint.name]?.error}
                      </div>
                    ) : (
                      <pre className="text-gray-300 text-sm overflow-x-auto">
                        {formatJson(responses[endpoint.name]?.data)}
                      </pre>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};

export default Sandbox;
