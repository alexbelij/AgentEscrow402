import React from 'react';

/**
 * FeatureStatus — a single source of truth for how the console labels the
 * maturity/verifiability of every capability. Applied to Feature Map rows,
 * and reusable anywhere else a status pill needs the same vocabulary.
 *
 * The five values are strict; anything ambiguous must be labelled
 * "Local demo" or "Planned", never elevated to "Live" or "On-chain" without
 * a checkable code/config anchor.
 *
 *  - `on-chain`          — backed by a deployed contract on Casper testnet
 *                          (hash present in the console `/contracts` view).
 *  - `live-api`          — implemented in the hosted REST API and callable
 *                          against the current backend (visible in `Docs`).
 *  - `local-demo`        — works in-process in the hosted console but has
 *                          no persistent on-chain or fully-external backing.
 *  - `simulation`        — runs a deterministic simulator/stub rather than
 *                          a real integration (e.g. VRF CSPRNG fallback).
 *  - `planned`           — described in the repo/roadmap but not wired into
 *                          the UI/API yet.
 */
export type FeatureStatusValue =
  | 'on-chain'
  | 'live-api'
  | 'local-demo'
  | 'simulation'
  | 'planned';

interface StatusMeta {
  label: string;
  cls: string;
  desc: string;
}

const STATUS_META: Record<FeatureStatusValue, StatusMeta> = {
  'on-chain': {
    label: 'On-chain',
    cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
    desc: 'Backed by a deployed Casper-testnet contract; hash is listed on the Contracts page.',
  },
  'live-api': {
    label: 'Live API',
    cls: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
    desc: 'Implemented in the hosted REST API and callable from the console.',
  },
  'local-demo': {
    label: 'Local demo',
    cls: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
    desc: 'Works in the hosted console for demonstration, but not persisted on-chain.',
  },
  simulation: {
    label: 'Simulation',
    cls: 'bg-purple-500/15 text-purple-300 border-purple-500/30',
    desc: 'A deterministic simulator/stub stands in for a real external integration.',
  },
  planned: {
    label: 'Planned',
    cls: 'bg-gray-500/15 text-gray-300 border-gray-500/30',
    desc: 'Documented in the repo/roadmap but not wired into the UI or API yet.',
  },
};

export function statusMeta(status: FeatureStatusValue): StatusMeta {
  return STATUS_META[status];
}

interface FeatureStatusProps {
  status: FeatureStatusValue;
  className?: string;
  showTooltip?: boolean;
}

/**
 * Small inline pill that renders one of the five canonical statuses. The
 * `title` attribute carries the long description so a viewer can hover to
 * see what the label actually means, without needing a legend on every
 * page that uses it.
 */
const FeatureStatus: React.FC<FeatureStatusProps> = ({ status, className = '', showTooltip = true }) => {
  const meta = STATUS_META[status];
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[11px] font-semibold uppercase tracking-wide ${meta.cls} ${className}`}
      title={showTooltip ? meta.desc : undefined}
      aria-label={`Status: ${meta.label}. ${meta.desc}`}
    >
      {meta.label}
    </span>
  );
};

export default FeatureStatus;
