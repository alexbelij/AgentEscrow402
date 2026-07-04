import React from 'react';
import ErrorBoundary from './ErrorBoundary';
import BackendWakeOverlay from './BackendWakeOverlay';
import WalletStatus from './WalletStatus';
import { Outlet, NavLink, useLocation } from 'react-router-dom';
import {
  Monitor,
  DollarSign,
  Users,
  Shield,
  Activity,
  FileText,
  FlaskConical,
  Bot,
  ChevronRight,
  Layers,
  Gavel,
} from 'lucide-react';

interface NavItem {
  name: string;
  path: string;
  icon: React.ElementType;
}

const navItems: NavItem[] = [
  { name: 'Overview', path: '/console/overview', icon: Monitor },
  { name: 'Escrows', path: '/console/escrows', icon: DollarSign },
  { name: 'Agents', path: '/console/agents', icon: Users },
  { name: 'Insurance', path: '/console/insurance', icon: Shield },
  { name: 'Risk', path: '/console/risk', icon: Activity },
  { name: 'Contracts', path: '/console/contracts', icon: FileText },
  { name: 'Advanced Escrow', path: '/console/advanced', icon: Layers },
  { name: 'Arbitration', path: '/console/arbitration', icon: Gavel },
  { name: 'Agent Demo', path: '/console/agent-demo', icon: Bot },
  { name: 'Sandbox', path: '/console/sandbox', icon: FlaskConical },
];

interface SectionInfo {
  title: string;
  desc: string;
  source: 'demo' | 'live' | 'tool';
}

// Per-route explanation shown as a banner so every console page tells the
// visitor what it is, what it is for, and whether the data is live or demo.
const SECTION_INFO: Record<string, SectionInfo> = {
  '/console/overview': {
    title: 'Console Overview',
    desc: 'Live health of the hosted API and Casper testnet target: persistence status, network mode, deployed contract and escrow volume. Use it to confirm the backend is reachable before running actions.',
    source: 'live',
  },
  '/console/escrows': {
    title: 'Escrows',
    desc: 'Every agent-to-agent payment is an escrow: funds are locked, then released, refunded or disputed. Create one, inspect its lifecycle, or act on it. Listed records are seeded demo data for the hosted console, not real on-chain transactions.',
    source: 'demo',
  },
  '/console/agents': {
    title: 'Agents',
    desc: 'Agent identities bind a service agent to a public key, capabilities and a reputation score, so counterparties can decide who to trust before locking funds. Listed agents are seeded demo identities for the hosted console.',
    source: 'demo',
  },
  '/console/insurance': {
    title: 'Insurance Pool',
    desc: 'A shared pool that pays out on covered disputes; a small fee on each escrow funds it, and premiums scale with counterparty risk. On the hosted console the pool is accounted off-chain (the pool contract is not yet deployed to testnet).',
    source: 'demo',
  },
  '/console/risk': {
    title: 'Risk Scoring',
    desc: 'An anomaly model scores counterparties and jobs so you can block or warn on high-risk deals before funds are locked, and feed the score into insurance pricing and arbitration routing. Scores shown use seeded demo data.',
    source: 'demo',
  },
  '/console/contracts': {
    title: 'Contract Playground',
    desc: 'A developer tool to call escrow contract actions (release, refund, dispute, VRF election) and read the raw API response. Actions only succeed on escrows in a valid state — a fresh pending escrow is provided for terminal-state actions.',
    source: 'tool',
  },
  '/console/advanced': {
    title: 'Advanced Escrow',
    desc: 'Three advanced escrow primitives beyond the basic lifecycle: escrow with a selectable token type (CSPR/CEP-18/CEP-78, one token per escrow), a linear streaming payout between a start and end time, and a commit-reveal hash-lock on an existing escrow. CEP-18/CEP-78 transfers are currently simulated backend-side, not real on-chain calls.',
    source: 'demo',
  },
  '/console/arbitration': {
    title: 'Arbitration',
    desc: 'AI-powered dispute evidence analysis (real LLM call with a deterministic heuristic fallback, tries Groq then NVIDIA NIM then a local model) and VRF-based neutral arbiter election, both run live against the real backend. In production these feed the escrow /dispute → /resolve lifecycle.',
    source: 'tool',
  },
  '/console/agent-demo': {
    title: 'Agent Demo',
    desc: 'A guided end-to-end walkthrough of an x402 agent payment: build the payment header, create an escrow, and release it — each step shows the exact request and live response.',
    source: 'tool',
  },
  '/console/sandbox': {
    title: 'API Sandbox',
    desc: 'An interactive explorer for every REST endpoint: pick a call on the left, set parameters, and see the live response. Use it to learn the API before wiring the SDK.',
    source: 'tool',
  },
};

const SOURCE_BADGE: Record<SectionInfo['source'], { label: string; cls: string }> = {
  live: { label: 'Live hosted API', cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
  demo: { label: 'Seeded demo data · not on-chain', cls: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
  tool: { label: 'Developer tool', cls: 'bg-sky-500/15 text-sky-300 border-sky-500/30' },
};

const ConsoleLayout: React.FC = () => {
  const location = useLocation();
  const pathnames = location.pathname.split('/').filter((x) => x);
  const info = SECTION_INFO[location.pathname];

  const getBreadcrumbs = () => {
    let currentPath = '';
    return pathnames.map((name, index) => {
      currentPath += `/${name}`;
      const isLast = index === pathnames.length - 1;
      const displayName = name.charAt(0).toUpperCase() + name.slice(1).replace(/-/g, ' ');
      return (
        <React.Fragment key={name}>
          <NavLink
            to={currentPath}
            className={`text-gray-400 hover:text-ae-accent transition-colors ${
              isLast ? 'font-semibold text-ae-accent' : ''
            }`}
          >
            {displayName}
          </NavLink>
          {!isLast && <ChevronRight className="h-4 w-4 text-gray-600 mx-1" />}
        </React.Fragment>
      );
    });
  };

  return (
    <div className="min-h-screen bg-ae-bg text-gray-100 flex flex-col">
      {/* Console section rail — one professional horizontal nav row on desktop and mobile. */}
      <div className="sticky top-14 z-40 bg-ae-card/95 backdrop-blur border-b border-ae-border">
        <div className="ae-section h-12 flex items-center overflow-x-auto no-scrollbar">
          <nav className="flex items-center gap-1 min-w-max">
            {navItems.map((item) => (
              <NavLink
                key={item.name}
                to={item.path}
                className={({ isActive }) =>
                  `flex items-center gap-1.5 px-3 py-2 rounded-full text-xs font-medium transition-colors whitespace-nowrap ${
                    isActive
                      ? 'bg-ae-accent/20 text-ae-accent border border-ae-accent/30'
                      : 'text-gray-400 hover:bg-ae-border/50 hover:text-gray-200 border border-transparent'
                  }`
                }
              >
                <item.icon className="h-3.5 w-3.5" />
                {item.name}
              </NavLink>
            ))}
          </nav>
        </div>
      </div>
      <WalletStatus />

      {/* Main Content Area */}
      <main className="flex-1 p-4 sm:p-6 lg:p-8">
        {/* Breadcrumbs */}
        <nav className="mb-6 hidden sm:flex items-center text-sm">
          <NavLink to="/" className="text-gray-400 hover:text-ae-accent transition-colors">
            Home
          </NavLink>
          <ChevronRight className="h-4 w-4 text-gray-600 mx-1" />
          {getBreadcrumbs()}
        </nav>
        {info && (
          <div className="mb-6 rounded-lg border border-ae-border bg-ae-card/60 p-4">
            <div className="flex flex-wrap items-center gap-3 mb-1.5">
              <h1 className="text-lg font-semibold text-gray-100">{info.title}</h1>
              <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full border ${SOURCE_BADGE[info.source].cls}`}>
                {SOURCE_BADGE[info.source].label}
              </span>
            </div>
            <p className="text-sm text-gray-400 leading-relaxed max-w-3xl">{info.desc}</p>
          </div>
        )}
        <ErrorBoundary>
          <Outlet />
        </ErrorBoundary>
      </main>
      <BackendWakeOverlay />
    </div>
  );
};

export default ConsoleLayout;
