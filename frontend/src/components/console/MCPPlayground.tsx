/**
 * Hosted MCP Playground — browse, inspect and dry-run the 26-tool MCP
 * server that ships with AE402.
 *
 * The page is a **read-first** builder tool: it lets a visitor pick a
 * tool, auto-renders a form from the tool's `inputSchema` (a JSON
 * Schema `object` with typed properties), and posts to
 * `POST /mcp/tools/{name}/call`. That server-side endpoint dispatches
 * the call in-process to the same REST route the underlying MCP tool
 * would use, so every existing guard (x402 payment fence, Observer
 * role fence, rate limiting) applies verbatim — there is no bypass
 * path here.
 *
 * Layout:
 *   [Left column]   catalogue list with search + category chips
 *   [Right column]  selected tool: description, schema, form,
 *                   Call button, response viewer.
 *
 * Kept intentionally lean — this is a builder tool, not a demo, so no
 * theatrical animations or "hosted demo" copy: the actual response
 * body is the star.
 */
import { useEffect, useMemo, useState } from 'react';
import { Search, PlayCircle, Copy, Check, Loader2, Terminal, BookOpen, ShieldAlert } from 'lucide-react';
import { useRole } from '../../lib/role';

interface ToolSchemaProperty {
  type?: string | string[];
  description?: string;
  enum?: unknown[];
  default?: unknown;
  minimum?: number;
  maximum?: number;
}

interface ToolInputSchema {
  type: string;
  properties?: Record<string, ToolSchemaProperty>;
  required?: string[];
  additionalProperties?: boolean;
}

interface McpTool {
  name: string;
  description: string;
  inputSchema: ToolInputSchema;
}

interface McpCatalogue {
  name: string;
  version: string;
  description?: string;
  tools: McpTool[];
}

interface McpCallResponse {
  content: { type: string; text: string }[];
  isError: boolean;
  status: number;
  tool: string;
}

// A best-effort category classifier so the left rail groups tools by
// purpose. Never authoritative — falls back to "Other".
function categorise(name: string): string {
  if (/escrow|release|refund|dispute|stream|batch/i.test(name)) return 'Escrow lifecycle';
  if (/reputation|registry|identity/i.test(name)) return 'Identity & reputation';
  if (/arbitr|elect|appeal/i.test(name)) return 'Arbitration';
  if (/risk/i.test(name)) return 'Risk';
  if (/x402|hash|header/i.test(name)) return 'x402 helpers';
  if (/stats|health|event|list_agents/i.test(name)) return 'Read-only';
  return 'Other';
}

function categoryColour(cat: string): string {
  switch (cat) {
    case 'Escrow lifecycle': return 'text-amber-300 border-amber-500/30 bg-amber-500/10';
    case 'Identity & reputation': return 'text-sky-300 border-sky-500/30 bg-sky-500/10';
    case 'Arbitration': return 'text-purple-300 border-purple-500/30 bg-purple-500/10';
    case 'Risk': return 'text-red-300 border-red-500/30 bg-red-500/10';
    case 'x402 helpers': return 'text-emerald-300 border-emerald-500/30 bg-emerald-500/10';
    case 'Read-only': return 'text-gray-300 border-gray-500/30 bg-gray-500/10';
    default: return 'text-gray-400 border-gray-500/20 bg-gray-500/5';
  }
}

const CATALOGUE_URL = '/backend/mcp/tools';
const CALL_URL = (name: string) => `/backend/mcp/tools/${encodeURIComponent(name)}/call`;

function jsonSample(schema: ToolInputSchema): string {
  const out: Record<string, unknown> = {};
  const props = schema.properties ?? {};
  for (const [key, prop] of Object.entries(props)) {
    if (prop.default !== undefined) {
      out[key] = prop.default;
      continue;
    }
    const type = Array.isArray(prop.type) ? prop.type[0] : prop.type;
    if (Array.isArray(prop.enum) && prop.enum.length) {
      out[key] = prop.enum[0];
      continue;
    }
    switch (type) {
      case 'integer':
      case 'number':
        out[key] = 0; break;
      case 'boolean':
        out[key] = false; break;
      case 'array':
        out[key] = []; break;
      case 'object':
        out[key] = {}; break;
      default:
        out[key] = '';
    }
  }
  return JSON.stringify(out, null, 2);
}

function CopyBtn({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        } catch { /* ignore */ }
      }}
      className="p-1.5 rounded-md text-gray-400 hover:text-gray-100 hover:bg-ae-border/50 outline-none focus-visible:ring-2 focus-visible:ring-ae-accent-bright"
      aria-label="Copy to clipboard"
    >
      {done ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}

const MCPPlayground: React.FC = () => {
  const { isObserver, blockedReason } = useRole();
  const [catalogue, setCatalogue] = useState<McpCatalogue | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [argsJson, setArgsJson] = useState('');
  const [argsErr, setArgsErr] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [response, setResponse] = useState<McpCallResponse | null>(null);
  const [callErr, setCallErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(CATALOGUE_URL);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const body = (await r.json()) as McpCatalogue;
        if (cancelled) return;
        setCatalogue(body);
        if (!selectedName && body.tools.length) setSelectedName(body.tools[0].name);
      } catch (e: any) {
        if (!cancelled) setLoadErr(e?.message ?? 'Failed to load MCP catalogue');
      }
    })();
    return () => { cancelled = true; };
  // Intentionally only on mount.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedTool = useMemo<McpTool | null>(() => {
    if (!catalogue || !selectedName) return null;
    return catalogue.tools.find((t) => t.name === selectedName) ?? null;
  }, [catalogue, selectedName]);

  // Reset the args + response when the tool changes.
  useEffect(() => {
    if (!selectedTool) return;
    setArgsJson(jsonSample(selectedTool.inputSchema));
    setArgsErr(null);
    setResponse(null);
    setCallErr(null);
  }, [selectedTool?.name]); // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = useMemo(() => {
    if (!catalogue) return [] as McpTool[];
    const q = query.trim().toLowerCase();
    if (!q) return catalogue.tools;
    return catalogue.tools.filter(
      (t) => t.name.toLowerCase().includes(q) || (t.description || '').toLowerCase().includes(q),
    );
  }, [catalogue, query]);

  const groups = useMemo(() => {
    const buckets = new Map<string, McpTool[]>();
    for (const t of filtered) {
      const c = categorise(t.name);
      const bucket = buckets.get(c) ?? [];
      bucket.push(t);
      buckets.set(c, bucket);
    }
    return Array.from(buckets.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [filtered]);

  async function onCall() {
    if (!selectedTool) return;
    setCallErr(null);
    setResponse(null);

    let parsedArgs: unknown;
    try {
      parsedArgs = argsJson.trim() ? JSON.parse(argsJson) : {};
      if (parsedArgs === null || typeof parsedArgs !== 'object' || Array.isArray(parsedArgs)) {
        throw new Error('arguments must be a JSON object');
      }
      setArgsErr(null);
    } catch (e: any) {
      setArgsErr(e?.message ?? 'invalid JSON');
      return;
    }

    setRunning(true);
    try {
      const r = await fetch(CALL_URL(selectedTool.name), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ arguments: parsedArgs }),
      });
      const raw = await r.text();
      let parsed: McpCallResponse | null = null;
      try { parsed = JSON.parse(raw) as McpCallResponse; } catch { /* ignore */ }
      if (!parsed) {
        setCallErr(`Non-JSON response (HTTP ${r.status}): ${raw.slice(0, 200)}`);
        return;
      }
      setResponse(parsed);
    } catch (e: any) {
      setCallErr(e?.message ?? 'Call failed');
    } finally {
      setRunning(false);
    }
  }

  if (loadErr) {
    return (
      <div className="p-6 rounded-lg border border-red-500/30 bg-red-500/10 text-red-300">
        Failed to load MCP tool catalogue: {loadErr}
      </div>
    );
  }

  if (!catalogue) {
    return (
      <div className="p-6 flex items-center gap-2 text-gray-400">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading MCP catalogue…
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-ae-border bg-ae-card/40 p-4 sm:p-5 flex flex-wrap items-start gap-4 justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm text-emerald-300 mb-1">
            <Terminal className="h-4 w-4" />
            <span className="font-mono">{catalogue.name} · v{catalogue.version}</span>
          </div>
          <p className="text-gray-400 text-sm max-w-3xl leading-relaxed">
            {catalogue.description ??
              'The 26-tool MCP server that ships with AE402 — same auth and role fence as every REST endpoint, since each tool dispatches in-process to its underlying HTTP route.'}
          </p>
        </div>
        <a
          href="https://github.com/alexbelij/AgentEscrow402/blob/main/docs/MCP_PLAYGROUND.md"
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 text-xs font-medium text-gray-300 hover:text-white border border-ae-border rounded-md px-2.5 py-1.5"
        >
          <BookOpen className="h-3.5 w-3.5" /> Docs
        </a>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,320px)_1fr] gap-6 items-start">
        {/* Left rail — catalogue */}
        <div className="rounded-lg border border-ae-border bg-ae-card/40 p-3">
          <div className="relative mb-3">
            <Search className="h-4 w-4 absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500" />
            <input
              type="text"
              placeholder={`Search ${catalogue.tools.length} tools`}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full pl-8 pr-3 py-2 text-sm rounded-md bg-ae-bg/60 border border-ae-border text-gray-100 placeholder:text-gray-500 focus:outline-none focus:border-ae-accent-bright"
            />
          </div>
          <div className="max-h-[65vh] overflow-y-auto space-y-3 pr-1">
            {groups.length === 0 && (
              <p className="text-xs text-gray-500 px-1 py-2">No tools match the search.</p>
            )}
            {groups.map(([cat, tools]) => (
              <div key={cat}>
                <div className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider mb-1.5 ${categoryColour(cat)}`}>
                  {cat}
                </div>
                <ul className="space-y-0.5">
                  {tools.map((t) => (
                    <li key={t.name}>
                      <button
                        type="button"
                        onClick={() => setSelectedName(t.name)}
                        className={`w-full text-left px-2 py-1.5 rounded-md text-sm border transition-colors ${
                          selectedName === t.name
                            ? 'border-ae-accent/40 bg-ae-accent/15 text-ae-accent-bright'
                            : 'border-transparent hover:bg-ae-border/40 text-gray-300 hover:text-white'
                        }`}
                      >
                        <span className="font-mono block truncate">{t.name}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>

        {/* Right — details & runner */}
        {selectedTool ? (
          <div className="space-y-4 min-w-0">
            <div className="rounded-lg border border-ae-border bg-ae-card/40 p-4">
              <div className="flex items-start gap-3 flex-wrap">
                <h2 className="font-mono text-lg text-white flex-1 min-w-0 truncate">{selectedTool.name}</h2>
                <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${categoryColour(categorise(selectedTool.name))}`}>
                  {categorise(selectedTool.name)}
                </span>
              </div>
              <p className="mt-2 text-sm text-gray-300 leading-relaxed">{selectedTool.description}</p>
              {(selectedTool.inputSchema.required?.length ?? 0) > 0 && (
                <p className="mt-2 text-xs text-gray-500">
                  Required: <span className="font-mono text-gray-300">{selectedTool.inputSchema.required?.join(', ')}</span>
                </p>
              )}
            </div>

            {/* Schema viewer */}
            <details className="rounded-lg border border-ae-border bg-ae-card/40 p-3 group">
              <summary className="cursor-pointer text-sm font-medium text-gray-300 select-none flex items-center justify-between">
                <span>Input schema</span>
                <span className="text-xs text-gray-500 group-open:hidden">click to expand</span>
              </summary>
              <div className="mt-3 relative">
                <pre className="text-xs font-mono text-gray-200 bg-ae-bg/70 border border-ae-border rounded-md p-3 overflow-x-auto max-h-[35vh]">
                  {JSON.stringify(selectedTool.inputSchema, null, 2)}
                </pre>
                <div className="absolute top-2 right-2">
                  <CopyBtn text={JSON.stringify(selectedTool.inputSchema, null, 2)} />
                </div>
              </div>
            </details>

            {/* Arguments editor */}
            <div className="rounded-lg border border-ae-border bg-ae-card/40 p-3">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-gray-200">Arguments (JSON)</span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setArgsJson(jsonSample(selectedTool.inputSchema))}
                    className="text-xs text-gray-400 hover:text-white"
                    title="Regenerate a starter body from the schema"
                  >
                    Reset to sample
                  </button>
                  <CopyBtn text={argsJson} />
                </div>
              </div>
              <textarea
                spellCheck={false}
                value={argsJson}
                onChange={(e) => setArgsJson(e.target.value)}
                rows={Math.max(4, Math.min(argsJson.split('\n').length + 1, 16))}
                className={`w-full font-mono text-xs px-3 py-2 rounded-md bg-ae-bg/70 border ${
                  argsErr ? 'border-red-500/40' : 'border-ae-border'
                } text-gray-100 focus:outline-none focus:border-ae-accent-bright resize-y`}
              />
              {argsErr && (
                <p className="mt-1.5 text-xs text-red-400 font-mono">JSON error: {argsErr}</p>
              )}
              <div className="mt-3 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={onCall}
                  disabled={running || isObserver}
                  title={isObserver ? blockedReason + ' (Observer can still browse the catalogue and inspect schemas.)' : undefined}
                  className="inline-flex items-center gap-2 rounded-md bg-emerald-600 hover:bg-emerald-500 disabled:bg-emerald-800/40 disabled:cursor-not-allowed text-white text-sm font-semibold px-4 py-2"
                >
                  {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlayCircle className="h-4 w-4" />}
                  Call tool
                </button>
                {isObserver && (
                  <span className="inline-flex items-center gap-1.5 text-xs text-amber-300">
                    <ShieldAlert className="h-3.5 w-3.5" /> Observer mode — calling is disabled. Switch to Driver in the header.
                  </span>
                )}
              </div>
            </div>

            {/* Response */}
            {callErr && (
              <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-red-300 text-sm">
                {callErr}
              </div>
            )}
            {response && (
              <div className={`rounded-lg border ${response.isError ? 'border-red-500/40' : 'border-emerald-500/40'} bg-ae-card/40 p-3`}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-medium text-gray-200">
                    Response · HTTP {response.status} · {response.isError ? 'error' : 'ok'}
                  </span>
                  <CopyBtn text={response.content.map((c) => c.text).join('\n\n')} />
                </div>
                <pre className="text-xs font-mono text-gray-100 bg-ae-bg/70 border border-ae-border rounded-md p-3 overflow-x-auto max-h-[45vh] whitespace-pre-wrap break-words">
                  {response.content.map((c) => c.text).join('\n\n')}
                </pre>
              </div>
            )}
          </div>
        ) : (
          <div className="rounded-lg border border-ae-border bg-ae-card/40 p-6 text-center text-gray-400">
            Select a tool from the catalogue on the left.
          </div>
        )}
      </div>
    </div>
  );
};

export default MCPPlayground;
