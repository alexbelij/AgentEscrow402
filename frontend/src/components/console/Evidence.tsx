import React, { useEffect, useState } from 'react';
import { ExternalLink, FileCheck, Loader2, Radio } from 'lucide-react';
import CopyButton from './CopyButton';

// Evidence page — links every deployed contract to its testnet.cspr.live
// deploy tx and its cspr.cloud contract explorer, so reviewers can verify
// the "REAL" claims in docs/REAL_VS_SIM.md on-chain in one click.
// Data source: /onchain.json (copied from deploy-out/onchain.json at build
// time). See AE402_AGENT_SPEC.md → A2.

interface ContractEvidence {
  key: string;
  name: string;
  contract_hash: string;
  contract_package_hash: string;
  deploy_hash: string;
  version: number;
  notes?: string;
  explorer?: string;
}

interface OnchainDoc {
  network: string;
  generated_at: string;
  contracts: Record<string, Omit<ContractEvidence, 'key'>>;
  api_url?: string;
  frontend_url?: string;
  source_ref?: string;
}

// Entry-point counts by contract, sourced from docs/ARCHITECTURE.md. Kept
// static so the page renders even when the backend is offline; if the
// canonical table drifts, update ARCHITECTURE.md and this map together.
const ENTRY_POINT_COUNTS: Record<string, number> = {
  escrow_manager_v9: 14,
  batch_escrow_manager: 5,
  insurance_pool: 7,
  vrf_arbiter: 8,
  agent_identity_registry: 9,
  multi_asset_escrow: 10,
  cep18_test_token_aetusd: 0, // CEP-18 standard entry points, external to us
  cep18_test_token_aemat: 0,
};

const stripHash = (h: string) => (h.startsWith('hash-') ? h.slice(5) : h);

const cleanDeployHash = (h: string) => (h.startsWith('hash-') ? h.slice(5) : h);

const Evidence: React.FC = () => {
  const [data, setData] = useState<OnchainDoc | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch('/onchain.json')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setData)
      .catch((e) => setError(e.message ?? String(e)));
  }, []);

  if (error) {
    return (
      <div className="p-6 text-red-400">
        <p>Failed to load on-chain evidence: {error}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="p-6 flex items-center gap-2 text-slate-400">
        <Loader2 className="w-4 h-4 animate-spin" />
        <span>Loading on-chain evidence…</span>
      </div>
    );
  }

  const entries: ContractEvidence[] = Object.entries(data.contracts).map(
    ([key, value]) => ({ key, ...value })
  );

  return (
    <div className="p-6 space-y-6">
      <header className="space-y-2">
        <div className="flex items-center gap-2">
          <FileCheck className="w-6 h-6 text-emerald-400" />
          <h1 className="text-2xl font-semibold">On-chain Evidence</h1>
        </div>
        <p className="text-slate-400 max-w-3xl">
          Every contract listed here is deployed on <strong>{data.network}</strong>.
          Each row links to the original deploy transaction (verifies the
          bytecode was posted on-chain, by whom, and when) and to the CSPR.cloud
          contract explorer (lets you inspect current state, entry points, and
          call history). Cross-reference with{' '}
          <code className="text-emerald-400">docs/REAL_VS_SIM.md</code>.
        </p>
        <p className="text-xs text-slate-500">
          Snapshot generated at {data.generated_at}
          {data.source_ref && <> · verified via {data.source_ref}</>}
        </p>
      </header>

      <div className="grid gap-4">
        {entries.map((c) => {
          const contractHash = stripHash(c.contract_hash);
          const deployHash = cleanDeployHash(c.deploy_hash);
          const entryPoints = ENTRY_POINT_COUNTS[c.key];
          return (
            <div
              key={c.key}
              className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 space-y-3"
            >
              <div className="flex items-start justify-between flex-wrap gap-2">
                <div>
                  <h2 className="font-semibold text-lg flex items-center gap-2">
                    <Radio className="w-4 h-4 text-emerald-400" />
                    {c.name}
                  </h2>
                  <p className="text-xs text-slate-500 mt-1">
                    key: <code className="text-slate-300">{c.key}</code> · version {c.version}
                    {entryPoints !== undefined && entryPoints > 0 && (
                      <> · {entryPoints} entry points</>
                    )}
                  </p>
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                  <a
                    href={`https://testnet.cspr.live/deploy/${deployHash}`}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 flex items-center gap-1"
                  >
                    Deploy tx <ExternalLink className="w-3 h-3" />
                  </a>
                  <a
                    href={`https://testnet.cspr.cloud/contract/${contractHash}`}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 flex items-center gap-1"
                  >
                    CSPR.cloud <ExternalLink className="w-3 h-3" />
                  </a>
                  <a
                    href={`https://testnet.cspr.live/contract/${contractHash}`}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 flex items-center gap-1"
                  >
                    CSPR.live <ExternalLink className="w-3 h-3" />
                  </a>
                </div>
              </div>

              <div className="grid gap-2 text-xs font-mono">
                <div className="flex items-center gap-2">
                  <span className="text-slate-500 w-32 shrink-0">contract_hash</span>
                  <code className="text-slate-300 break-all">{contractHash}</code>
                  <CopyButton text={contractHash} />
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-slate-500 w-32 shrink-0">package_hash</span>
                  <code className="text-slate-300 break-all">{stripHash(c.contract_package_hash)}</code>
                  <CopyButton text={stripHash(c.contract_package_hash)} />
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-slate-500 w-32 shrink-0">deploy_hash</span>
                  <code className="text-slate-300 break-all">{deployHash}</code>
                  <CopyButton text={deployHash} />
                </div>
              </div>

              {c.notes && (
                <p className="text-xs text-amber-400/80 italic">Note: {c.notes}</p>
              )}
            </div>
          );
        })}
      </div>

      <footer className="text-xs text-slate-500 pt-4 border-t border-slate-800">
        {data.api_url && (
          <p>
            API:{' '}
            <a
              href={data.api_url}
              className="text-emerald-400 hover:underline"
              target="_blank"
              rel="noreferrer"
            >
              {data.api_url}
            </a>
          </p>
        )}
        {data.frontend_url && (
          <p>
            Frontend:{' '}
            <a
              href={data.frontend_url}
              className="text-emerald-400 hover:underline"
              target="_blank"
              rel="noreferrer"
            >
              {data.frontend_url}
            </a>
          </p>
        )}
      </footer>
    </div>
  );
};

export default Evidence;
