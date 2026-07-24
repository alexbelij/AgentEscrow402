import React, { useEffect, useState } from 'react';
import { useNotifications } from '../../hooks/useNotifications';
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
  ChevronsLeft,
  ChevronsRight,
  Layers,
  Gavel,
  BadgeCheck,
  Sparkles,
  Menu,
  X,
  Github,
  BookOpen,
  Compass,
} from 'lucide-react';

interface NavItem {
  name: string;
  path: string;
  icon: React.ElementType;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

// Grouped by product purpose (five audiences of the same console):
//   - Core escrow          — the lifecycle that moves money.
//   - Trust & resolution   — who to trust, how disagreements are settled.
//   - Operations           — the risk / insurance / infra layer around it.
//   - Developer tools      — anything a builder needs to wire an agent up.
//   - Explore              — narrative / map entry points into the same UI.
// Every route from the previous flat/three-group layout is preserved; no
// section is hidden, moved off /console, or renamed. Only the sidebar
// headings and their ordering change.
const NAV_GROUPS: NavGroup[] = [
  {
    label: 'Core escrow',
    items: [
      { name: 'Escrows', path: '/console/escrows', icon: DollarSign },
      { name: 'Advanced Escrow', path: '/console/advanced', icon: Layers },
    ],
  },
  {
    label: 'Trust & resolution',
    items: [
      { name: 'Arbitration', path: '/console/arbitration', icon: Gavel },
      { name: 'Identity Registry', path: '/console/identity-registry', icon: BadgeCheck },
      { name: 'Agents', path: '/console/agents', icon: Users },
      { name: 'Evidence', path: '/console/evidence', icon: FileText },
    ],
  },
  {
    label: 'Operations',
    items: [
      { name: 'Insurance', path: '/console/insurance', icon: Shield },
      { name: 'Risk', path: '/console/risk', icon: Activity },
      { name: 'Contracts', path: '/console/contracts', icon: FileText },
    ],
  },
  {
    label: 'Developer tools',
    items: [
      { name: 'Sandbox', path: '/console/sandbox', icon: FlaskConical },
      { name: 'Agent Demo', path: '/console/agent-demo', icon: Bot },
      { name: 'API / SDK / MCP Docs', path: '/console/docs', icon: BookOpen },
    ],
  },
  {
    label: 'Explore',
    items: [
      { name: 'Overview', path: '/console/overview', icon: Monitor },
      { name: 'Use Cases', path: '/console/use-cases', icon: Sparkles },
      { name: 'Feature Map', path: '/console/feature-map', icon: Compass },
    ],
  },
];
const ALL_ITEMS = NAV_GROUPS.flatMap((g) => g.items);

interface SectionInfo {
  title: string;
  desc: string;
  source: 'demo' | 'live' | 'tool' | 'guide';
}

// Per-route explanation shown once, right under the page title, so every
// console page tells the visitor what it is, what it is for, and whether the
// data is live or demo — pages themselves must not repeat this.
const SECTION_INFO: Record<string, SectionInfo> = {
  '/console/overview': {
    title: 'Console Overview',
    desc: 'Live health of the hosted API and Casper testnet target: persistence status, network mode, deployed contract and escrow volume. Use it to confirm the backend is reachable before running actions.',
    source: 'live',
  },
  '/console/use-cases': {
    title: 'Use Cases',
    desc: 'Four narrative scenarios for non-technical reviewers — what AE402 is for, in plain language — with each step linking straight into the real panel that runs it (Escrows, Arbitration, Identity Registry, Advanced Escrow, Insurance, Risk). No separate logic: this page is a guided front door to the same live console.',
    source: 'guide',
  },
  '/console/escrows': {
    title: 'Escrows',
    desc: 'Every agent-to-agent payment is an escrow: funds are locked, then released, refunded or disputed. Create one, inspect its lifecycle, or act on it. Listed records are real API/DB rows from the Casper testnet-backed hosted console — create your own below to see a live row join them.',
    source: 'demo',
  },
  '/console/agents': {
    title: 'Agents',
    desc: 'Agent identities bind a service agent to a public key, capabilities and a reputation score, so counterparties can decide who to trust before locking funds. Listed agents are real API/DB rows from the hosted console — register your own below to see it join the list.',
    source: 'demo',
  },
  '/console/insurance': {
    title: 'Insurance Pool',
    desc: 'A shared pool that pays out on covered disputes; a small fee on each escrow funds it, and premiums scale with counterparty risk. The insurance-pool contract is deployed on testnet (ead90738…); on the hosted console, pool accounting is managed server-side.',
    source: 'demo',
  },
  '/console/risk': {
    title: 'Risk Scoring',
    desc: 'An anomaly model scores counterparties and jobs so you can block or warn on high-risk deals before funds are locked, and feed the score into insurance pricing and arbitration routing. Scores shown are computed live over the seeded testnet escrow dataset above, not static placeholders.',
    source: 'demo',
  },
  '/console/contracts': {
    title: 'Contract Playground',
    desc: 'A developer tool to call escrow contract actions (release, refund, dispute, VRF election) and read the raw API response. Actions only succeed on escrows in a valid state — a fresh pending escrow is provided for terminal-state actions.',
    source: 'tool',
  },
  '/console/advanced': {
    title: 'Advanced Escrow',
    desc: 'Three advanced escrow primitives beyond the basic lifecycle: escrow with a selectable token type (CSPR/CEP-18/CEP-78, one token per escrow), a linear streaming payout between a start and end time, and a commit-reveal hash-lock on an existing escrow. CEP-18 and CEP-78 transfers are both real on-chain calls against deployed testnet contracts.',
    source: 'demo',
  },
  '/console/arbitration': {
    title: 'Arbitration',
    desc: 'AI-powered dispute evidence analysis (real LLM call with a deterministic heuristic fallback, tries Groq then NVIDIA NIM then a local model) and VRF-based neutral arbiter election, both run live against the real backend. In production these feed the escrow /dispute → /resolve lifecycle.',
    source: 'live',
  },
  '/console/identity-registry': {
    title: 'Identity Registry',
    desc: 'A DID reputation/staking layer (real backend, in-memory in this sandbox): register a did:casper:<account> identity, record completed/disputed deals to build cumulative reputation, apply time-based reputation decay, slash stake for bad behavior, advance verification level, and search agents by capability/reputation/verification. Separate from the public-key identity + capability delegation registry on the Agents page.',
    source: 'live',
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
  '/console/docs': {
    title: 'API / SDK / MCP Documentation',
    desc: 'Complete reference for all 62 REST API endpoints, the Python SDK with code examples, LangChain integration, and the 26-tool MCP server for AI agent interoperability.',
    source: 'tool',
  },
  '/console/evidence': {
    title: 'Evidence Bundle',
    desc: 'Attach and inspect the evidence a dispute is being decided on — the payload the arbitration analyzer consumes when a case is opened. Kept alongside Arbitration and Agents so a reviewer can walk a dispute end-to-end without leaving the console.',
    source: 'demo',
  },
  '/console/feature-map': {
    title: 'Feature Map',
    desc: 'A single, read-only inventory of every capability the console exposes, grouped by purpose, with a strict status label on each row (On-chain, Live API, Local demo, Simulation, Planned) so it is easy to tell at a glance what is backed by a deployed contract versus a hosted demo or a simulator.',
    source: 'guide',
  },
};

// "demo" here means "real hosted API + DB records that were seeded for this
// console, not activity from your own actions" — never a fake/static
// placeholder. The badge and copy call this out explicitly (testnet /
// seeded record, not "demo" alone) so it doesn't read as a stub.
const SOURCE_BADGE: Record<SectionInfo['source'], { label: string; cls: string }> = {
  live: { label: 'Live hosted API', cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
  demo: { label: 'Testnet · seeded records', cls: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
  tool: { label: 'Developer tool', cls: 'bg-sky-500/15 text-sky-300 border-sky-500/30' },
  guide: { label: 'Guided walkthrough', cls: 'bg-purple-500/15 text-purple-300 border-purple-500/30' },
};

const SIDEBAR_STORAGE_KEY = 'ae402_console_sidebar_collapsed';

function NavRow({ item, collapsed, onNavigate }: { item: NavItem; collapsed: boolean; onNavigate?: () => void }) {
  const Icon = item.icon;
  return (
    <NavLink
      to={item.path}
      onClick={onNavigate}
      title={collapsed ? item.name : undefined}
      className={({ isActive }) =>
        `group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ae-accent-bright focus-visible:ring-offset-2 focus-visible:ring-offset-ae-bg ${
          isActive
            ? 'bg-ae-accent/20 text-ae-accent-bright border border-ae-accent/40'
            : 'text-gray-400 hover:bg-ae-border/50 hover:text-gray-100 border border-transparent'
        } ${collapsed ? 'justify-center' : ''}`
      }
    >
      <Icon className="h-[18px] w-[18px] shrink-0" aria-hidden="true" />
      {!collapsed && <span className="truncate">{item.name}</span>}
      {collapsed && (
        <span
          role="tooltip"
          className="pointer-events-none absolute left-full top-1/2 -translate-y-1/2 ml-2 whitespace-nowrap rounded-md border border-ae-border bg-ae-card px-2.5 py-1.5 text-xs font-medium text-gray-100 opacity-0 shadow-lg transition-opacity duration-100 group-hover:opacity-100 group-focus-visible:opacity-100 z-50"
        >
          {item.name}
        </span>
      )}
    </NavLink>
  );
}

function SidebarNav({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  return (
    <nav className="flex-1 overflow-y-auto px-2 py-3 space-y-4">
      {NAV_GROUPS.map((group, gi) => (
        <div key={group.label || `g${gi}`}>
          {group.label && !collapsed && (
            <div className="px-3 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-gray-600">
              {group.label}
            </div>
          )}
          {group.label && collapsed && gi > 0 && <div className="mx-2 mb-2 border-t border-ae-border/70" aria-hidden="true" />}
          <div className="space-y-1">
            {group.items.map((item) => (
              <NavRow key={item.path} item={item} collapsed={collapsed} onNavigate={onNavigate} />
            ))}
          </div>
        </div>
      ))}
    </nav>
  );
}

const ConsoleLayout: React.FC = () => {
  // Subscribes to backend SSE and fires toast on escrow lifecycle events.
  // Mounted only inside /console so the marketing landing stays quiet.
  useNotifications();
  const location = useLocation();
  const pathnames = location.pathname.split('/').filter((x) => x);
  const info = SECTION_INFO[location.pathname];

  const [collapsed, setCollapsed] = useState(() => {
    if (typeof window === 'undefined') return false;
    return window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === '1';
  });
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, collapsed ? '1' : '0');
  }, [collapsed]);

  useEffect(() => {
    setMobileNavOpen(false);
  }, [location.pathname]);

  const currentPage = ALL_ITEMS.find((i) => i.path === location.pathname);

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
    <div className="min-h-screen bg-ae-bg text-gray-100">
      {/* Desktop sidebar — true dashboard layout: fixed, full viewport
          height (own logo row included, not shared with any top navbar),
          collapsible icon rail (icon + hover/focus tooltip) or full labels.
          overflow-x-hidden guarantees the collapse animation never produces
          a horizontal scrollbar mid-transition. */}
      <aside
        className={`hidden lg:flex flex-col fixed left-0 top-0 h-screen z-40 border-r border-ae-border bg-ae-card/60 overflow-x-hidden transition-[width] duration-200 ${
          collapsed ? 'w-16' : 'w-64'
        }`}
      >
        <a
          href="/"
          className={`flex items-center gap-2 h-14 border-b border-ae-border/70 shrink-0 overflow-hidden ${
            collapsed ? 'justify-center px-0' : 'px-3'
          }`}
        >
          <img src="/images/logo.webp" alt="AE402" className="h-6 w-6 shrink-0" />
          {!collapsed && <span className="font-bold text-white text-sm truncate">AgentEscrow402</span>}
        </a>
        <div className="flex items-center justify-end px-2 py-2 border-b border-ae-border/70 shrink-0">
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            aria-expanded={!collapsed}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className="p-2 rounded-lg text-gray-400 hover:text-gray-100 hover:bg-ae-border/50 outline-none focus-visible:ring-2 focus-visible:ring-ae-accent-bright"
          >
            {collapsed ? <ChevronsRight className="h-4 w-4" /> : <ChevronsLeft className="h-4 w-4" />}
          </button>
        </div>
        <SidebarNav collapsed={collapsed} />
      </aside>

      {/* Mobile nav drawer — the single menu on small screens: it already
          contains every sidebar section, so there is no separate "site
          menu" burger anywhere on console pages. Always mounted (not
          conditionally rendered) so the open/close transform transition can
          actually animate both ways instead of popping in/out instantly. */}
      <div
        className={`lg:hidden fixed inset-0 z-[70] flex transition-opacity duration-300 ${
          mobileNavOpen ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'
        }`}
        aria-hidden={!mobileNavOpen}
      >
        <div className="absolute inset-0 bg-black/60" onClick={() => setMobileNavOpen(false)} aria-hidden="true" />
        <div
          className={`relative w-72 max-w-[85vw] h-full bg-ae-card border-r border-ae-border flex flex-col transition-transform duration-300 ease-out ${
            mobileNavOpen ? 'translate-x-0' : '-translate-x-full'
          }`}
        >
          <div className="flex items-center justify-between px-3 py-3 border-b border-ae-border/70">
            <a href="/" className="flex items-center gap-2">
              <img src="/images/logo.webp" alt="AE402" className="h-6 w-6 shrink-0" />
              <span className="font-bold text-white text-sm truncate">AgentEscrow402</span>
            </a>
            <button
              type="button"
              onClick={() => setMobileNavOpen(false)}
              aria-label="Close menu"
              className="p-2 rounded-lg text-gray-400 hover:text-gray-100 hover:bg-ae-border/50"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          <SidebarNav collapsed={false} onNavigate={() => setMobileNavOpen(false)} />
          <div className="border-t border-ae-border/70 px-3 py-3 flex items-center justify-between shrink-0">
            <a
              href="/"
              className="text-xs font-medium text-gray-400 hover:text-gray-100 transition-colors"
            >
              ← Back to landing
            </a>
            <a
              href="https://github.com/alexbelij/AgentEscrow402"
              target="_blank"
              rel="noreferrer"
              aria-label="View source on GitHub"
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-100 hover:bg-ae-border/50"
            >
              <Github className="h-4 w-4" />
            </a>
          </div>
        </div>
      </div>

      {/* Right column — offset by the sidebar's current width via padding
          (not a fixed+left calc), so the top bar below (sticky, in normal
          flow) is automatically confined to this column's box and can
          never overlap the sidebar or get overlapped itself. */}
      <div className={`flex flex-col min-h-screen transition-[padding] duration-200 ${collapsed ? 'lg:pl-16' : 'lg:pl-64'}`}>
        {/* Sticky top bar for this column only: mobile burger row (mobile
            only) stacked above the wallet/demo-mode bar. Both are in
            normal document flow, so main content below can never be
            covered by either. */}
        <div className="sticky top-0 z-30">
          <div className="lg:hidden flex items-center gap-2 border-b border-ae-border bg-ae-card/95 backdrop-blur px-4 py-2.5">
            <button
              type="button"
              onClick={() => setMobileNavOpen(true)}
              aria-label="Open console menu"
              className="p-2 -ml-2 rounded-lg text-gray-300 hover:text-gray-100 hover:bg-ae-border/50 outline-none focus-visible:ring-2 focus-visible:ring-ae-accent-bright"
            >
              <Menu className="h-5 w-5" />
            </button>
            <span className="text-sm font-semibold text-gray-200 truncate">{currentPage?.name || 'Console'}</span>
          </div>
          <WalletStatus />
        </div>

        {/* Main Content Area — full width, no artificial max-width, so the
            sidebar's fixed rail is the only width constraint. */}
        <main className="flex-1 w-full px-4 sm:px-6 lg:px-8 py-6">
          <nav className="mb-6 hidden sm:flex items-center text-sm" aria-label="Breadcrumb">
            <NavLink to="/" className="text-gray-400 hover:text-ae-accent transition-colors">
              Home
            </NavLink>
            <ChevronRight className="h-4 w-4 text-gray-600 mx-1" />
            {getBreadcrumbs()}
          </nav>

          {info && (
            <div className="mb-6">
              <div className="flex flex-wrap items-center gap-3 mb-2">
                <h1 className="text-2xl font-bold text-gray-50">{info.title}</h1>
                <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full border ${SOURCE_BADGE[info.source].cls}`}>
                  {SOURCE_BADGE[info.source].label}
                </span>
              </div>
              <p className="w-full text-sm text-gray-400 leading-relaxed">{info.desc}</p>
            </div>
          )}

          <ErrorBoundary>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
      <BackendWakeOverlay />
    </div>
  );
};

export default ConsoleLayout;
