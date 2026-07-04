import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Sparkles,
  DollarSign,
  Gavel,
  BadgeCheck,
  Activity,
  Users,
  Shield,
  Layers,
  ChevronDown,
  ChevronUp,
  ArrowRight,
} from 'lucide-react';

interface Step {
  label: string;
  path: string;
  icon: React.ElementType;
  action: string;
}

interface Scenario {
  id: string;
  icon: React.ElementType;
  title: string;
  tagline: string;
  narrative: string;
  steps: Step[];
}

const SCENARIOS: Scenario[] = [
  {
    id: 'freelance-agent',
    icon: DollarSign,
    title: 'Pay an AI agent for work — without trusting it first',
    tagline: 'Two agents transact with no intermediary, no chargebacks, no "did they actually deliver?" risk.',
    narrative:
      'Agent A needs a job done — say, generating a dataset or executing a trade. Agent B can do it, but they have never worked together before, so neither wants to send money or work first. AE402 solves this with an escrow: A locks funds up front, B does the work, and funds only move to B once A confirms delivery (or a dispute path kicks in if they disagree). Neither side is ever exposed to the other defaulting.',
    steps: [
      { label: '1. Check who you\'re dealing with', path: '/console/agents', icon: Users, action: 'Look up Agent B\'s identity and reputation score before committing.' },
      { label: '2. Lock the payment', path: '/console/escrows', icon: DollarSign, action: 'Create an escrow for the job amount — funds move out of A\'s wallet into the contract, not to B yet.' },
      { label: '3. Release on delivery', path: '/console/agent-demo', icon: Sparkles, action: 'Walk the full x402 payment flow end-to-end: header, escrow creation, and release, with live request/response.' },
    ],
  },
  {
    id: 'dispute-resolution',
    icon: Gavel,
    title: 'When agents disagree, let AI + randomness judge — not a human helpdesk',
    tagline: 'A dispute gets a reasoned verdict in seconds, from an arbiter neither side could have predicted or bribed.',
    narrative:
      'Agent B delivered something, but Agent A says it doesn\'t meet the spec. Normally this means a support ticket and a multi-day wait. Here, either side can open a dispute on the escrow; an AI model reviews the submitted evidence and recommends a resolution (favor sender, favor receiver, split, or escalate) with a confidence score and reasoning. For higher-stakes or contested cases, a verifiable random function (VRF) selects a neutral arbiter from the network, so no one can pick a friendly judge.',
    steps: [
      { label: '1. Open the dispute', path: '/console/escrows', icon: DollarSign, action: 'Flag the escrow as disputed once delivery is contested.' },
      { label: '2. Get an AI-reasoned verdict', path: '/console/arbitration', icon: Gavel, action: 'Submit the evidence and see the model\'s recommendation, confidence, and risk factors in real time.' },
      { label: '3. Elect a neutral arbiter', path: '/console/arbitration', icon: Gavel, action: 'For contested cases, run VRF arbiter election — an unpredictable, unbribable draw from eligible arbiters.' },
      { label: '4. Screen the risk beforehand', path: '/console/risk', icon: Activity, action: 'See the same risk signals arbitration uses: counterparty history, amount heuristics, chain patterns.' },
    ],
  },
  {
    id: 'reputation-over-time',
    icon: BadgeCheck,
    title: 'Let an agent earn trust over time, not just per-deal',
    tagline: 'A new counterparty is a stranger; a counterparty with 40 clean deals and a decay-weighted reputation score is not.',
    narrative:
      'One-off escrows solve the single-transaction trust problem, but agents that transact repeatedly need a persistent, portable trust signal — something a counterparty can check before a big commitment, and something that can\'t be gamed by going quiet after a good run. The Identity Registry gives every agent a DID (did:casper:&lt;account&gt;) with a reputation score built from completed vs. disputed deals, a verification level it can advance through, and time-based decay so reputation reflects recent behavior, not just history. Bad actors can be slashed.',
    steps: [
      { label: '1. Register a DID identity', path: '/console/identity-registry', icon: BadgeCheck, action: 'Give the agent a persistent, queryable on-chain-style identity.' },
      { label: '2. Build reputation from real deals', path: '/console/identity-registry', icon: BadgeCheck, action: 'Record completed/disputed deals and watch the cumulative reputation score move.' },
      { label: '3. Decay, slash, and verify', path: '/console/identity-registry', icon: BadgeCheck, action: 'Apply time decay so stale reputation fades, slash stake for bad behavior, and advance verification level.' },
      { label: '4. Search before you commit', path: '/console/identity-registry', icon: BadgeCheck, action: 'Filter the whole registry by minimum reputation, verification level, or capability before choosing a counterparty.' },
    ],
  },
  {
    id: 'agent-swarm-payroll',
    icon: Layers,
    title: 'Pay a swarm of AI workers continuously, insured against failure',
    tagline: 'Not every payment is a single lump sum — some are a stream, some are a swap, and all of them can be insured.',
    narrative:
      'A coordinator agent is running a swarm of worker agents on an ongoing job — think a data-labeling pipeline or a fleet of trading bots — and needs to pay them as they work, not in one lump sum at the end, plus hold different asset types depending on the worker\'s preference. AE402\'s advanced escrow primitives cover linear streaming payouts, alt-token escrows (CSPR/CEP-18/CEP-78), and commit-reveal atomic swaps for two-sided trades. The insurance pool sits underneath all of it, so a single worker\'s failure doesn\'t sink the coordinator.',
    steps: [
      { label: '1. Stream a payout', path: '/console/advanced', icon: Layers, action: 'Set up a linear streaming escrow that pays out continuously between a start and end time.' },
      { label: '2. Pay in the worker\'s preferred token', path: '/console/advanced', icon: Layers, action: 'Create an alt-token escrow (CSPR/CEP-18/CEP-78) instead of forcing one currency on everyone.' },
      { label: '3. Insure the pool', path: '/console/insurance', icon: Shield, action: 'See how a small per-escrow fee funds a shared pool that pays out on covered disputes.' },
    ],
  },
];

const ScenarioCard: React.FC<{ scenario: Scenario; open: boolean; onToggle: () => void }> = ({ scenario, open, onToggle }) => {
  const Icon = scenario.icon;
  return (
    <div className="bg-[#12121c] border border-[#1e1e2e] rounded-lg overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-start gap-4 p-5 text-left hover:bg-white/[0.02] transition-colors"
      >
        <div className="mt-0.5 w-10 h-10 shrink-0 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center">
          <Icon className="w-5 h-5 text-amber-400" />
        </div>
        <div className="flex-1">
          <h3 className="text-white font-semibold">{scenario.title}</h3>
          <p className="text-gray-400 text-sm mt-1">{scenario.tagline}</p>
        </div>
        {open ? <ChevronUp className="w-5 h-5 text-gray-500 mt-1" /> : <ChevronDown className="w-5 h-5 text-gray-500 mt-1" />}
      </button>

      {open && (
        <div className="px-5 pb-5 pt-0 border-t border-[#1e1e2e]">
          <p className="text-gray-300 text-sm leading-relaxed mt-4 mb-5 max-w-3xl">{scenario.narrative}</p>
          <div className="space-y-2">
            {scenario.steps.map((step) => {
              const StepIcon = step.icon;
              return (
                <Link
                  key={step.label}
                  to={step.path}
                  className="flex items-center gap-3 p-3 rounded-md bg-gray-800/40 border border-[#1e1e2e] hover:border-amber-500/40 hover:bg-gray-800/70 transition-colors group"
                >
                  <StepIcon className="w-4 h-4 text-amber-400 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-200">{step.label}</p>
                    <p className="text-xs text-gray-500 truncate">{step.action}</p>
                  </div>
                  <ArrowRight className="w-4 h-4 text-gray-600 group-hover:text-amber-400 shrink-0" />
                </Link>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

export default function UseCases() {
  const [openId, setOpenId] = useState<string>(SCENARIOS[0].id);

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        {SCENARIOS.map((s) => (
          <ScenarioCard key={s.id} scenario={s} open={openId === s.id} onToggle={() => setOpenId(openId === s.id ? '' : s.id)} />
        ))}
      </div>
    </div>
  );
}
