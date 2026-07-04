import React, { useState, useEffect } from 'react';
import { api, CreateEscrowRequest, EscrowActionRequest, DEMO_AGENT_RECEIVER, buildDemoXPaymentHeader } from '../../lib/api';
import { csprToMotes } from '../../lib/format';
import {
  Play,
  RefreshCw,
  CheckCircle,
  XCircle,
  Hourglass,
  Bot,
  DollarSign,
  Send,
  Undo2,
  AlertTriangle,
  Star,
  Loader2,
  ChevronRight,
  Eye,
  PlusCircle,
} from 'lucide-react';

interface DemoStep {
  id: number;
  name: string;
  description: string;
  icon: React.ElementType;
  status: 'pending' | 'loading' | 'success' | 'error';
  response: any;
  action?: () => Promise<any>;
  disabled?: boolean;
}

const CodeBlock: React.FC<{ children: string; title?: string }> = ({ children, title }) => (
  <div className="bg-gray-800 rounded-md p-4 text-sm font-mono text-gray-300 overflow-x-auto">
    {title && <p className="text-gray-400 mb-2">{title}</p>}
    <pre>{children}</pre>
  </div>
);

const AgentDemo: React.FC = () => {
  const [currentStep, setCurrentStep] = useState(0);
  const [escrowHash, setEscrowHash] = useState<string | null>(null);
  const [demoSteps, setDemoSteps] = useState<DemoStep[]>([]);
  const [overallLoading, setOverallLoading] = useState(false);
  const [overallError, setOverallError] = useState<string | null>(null);

  // Generate a fresh 64-char hex service hash for each demo run so the escrow is unique.
  const randomHex64 = () => {
    const bytes = new Uint8Array(32);
    (window.crypto || (window as any).msCrypto).getRandomValues(bytes);
    return Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('');
  };
  const [serviceHash, setServiceHash] = useState<string>(randomHex64());

  const examplePayee = DEMO_AGENT_RECEIVER;
  const exampleAmountCspr = 100; // 100 CSPR -> converted to motes below

  const resetDemo = () => {
    const freshHash = randomHex64();
    setServiceHash(freshHash);
    setCurrentStep(0);
    setEscrowHash(null);
    setOverallLoading(false);
    setOverallError(null);
    initializeSteps(freshHash);
  };

  const initializeSteps = (hashForRun = serviceHash) => {
    setDemoSteps([
      {
        id: 1,
        name: 'Create Escrow',
        description: 'An AI agent (Payer) initiates an escrow for a service with another AI agent (Payee).',
        icon: PlusCircle,
        status: 'pending',
        response: null,
        action: async () => {
          const req: CreateEscrowRequest = {
            receiver: examplePayee,
            amount: csprToMotes(exampleAmountCspr),
            service_hash: hashForRun,
            ttl: 300,
          };
          const res = await api.createEscrow(req);
          // The escrow is addressed by its service_hash for all later actions.
          if (res.data && !res.error) {
            setEscrowHash((res.data as any).service_hash || hashForRun);
          }
          return res;
        },
      },
      {
        id: 2,
        name: 'View Escrow Status',
        description: 'The agents check the current status of the created escrow.',
        icon: Eye,
        status: 'pending',
        response: null,
        action: async () => {
          const targetHash = escrowHash || hashForRun;
          return await api.getEscrowByHash(targetHash);
        },
      },
      {
        id: 3,
        name: 'Release Escrow',
        description: 'Upon service completion, the Payer (or Arbiter) releases funds to the Payee.',
        icon: Send,
        status: 'pending',
        response: null,
        action: async () => {
          const targetHash = escrowHash || hashForRun;
          const req: EscrowActionRequest = { service_hash: targetHash };
          return await api.releaseEscrow(req);
        },
      },
      {
        id: 4,
        name: 'Check Reputation',
        description: 'The Payer checks the Payee\'s reputation after a successful transaction.',
        icon: Star,
        status: 'pending',
        response: null,
        action: async () => {
          return await api.getReputation(examplePayee);
        },
      },
    ]);
  };

  useEffect(() => {
    initializeSteps();
  }, [serviceHash]); // Re-initialize only for a fresh demo hash; keep step responses visible during a run

  const runStep = async (stepIndex: number) => {
    if (overallLoading) return; // Prevent multiple steps running concurrently

    const step = demoSteps[stepIndex];
    if (!step || step.disabled || !step.action) return;

    setOverallLoading(true);
    setOverallError(null);

    setDemoSteps((prev) =>
      prev.map((s, i) => (i === stepIndex ? { ...s, status: 'loading', response: null } : s))
    );

    try {
      const res = await step.action();
      if (res.error) throw new Error(res.error);

      setDemoSteps((prev) =>
        prev.map((s, i) =>
          i === stepIndex ? { ...s, status: 'success', response: res.data } : s
        )
      );
      setCurrentStep(stepIndex + 1); // Move to next step
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'An unknown error occurred.';
      setDemoSteps((prev) =>
        prev.map((s, i) =>
          i === stepIndex ? { ...s, status: 'error', response: { error: errorMessage } } : s
        )
      );
      setOverallError(`Step ${step.id} failed: ${errorMessage}`);
    } finally {
      setOverallLoading(false);
    }
  };

  const getStatusColor = (status: DemoStep['status']) => {
    switch (status) {
      case 'pending': return 'text-gray-500';
      case 'loading': return 'text-amber-500';
      case 'success': return 'text-green-500';
      case 'error': return 'text-red-500';
      default: return 'text-gray-500';
    }
  };

  const displayStep = demoSteps.find((s) => s.status === 'loading') || [...demoSteps].reverse().find((s) => s.response) || demoSteps[currentStep] || demoSteps[0];

  const renderRequestPreview = (step?: DemoStep) => {
    if (!step) return null;
    if (step.id === 1) {
      return (
        <div className="space-y-3">
          <CodeBlock title="Request Body (POST /escrow)">{JSON.stringify({ receiver: examplePayee, amount: csprToMotes(exampleAmountCspr), service_hash: serviceHash, ttl: 300 }, null, 2)}</CodeBlock>
          <CodeBlock title="Demo identity header (generated by frontend)">{`X-Payment: ${buildDemoXPaymentHeader(serviceHash, csprToMotes(exampleAmountCspr)).slice(0, 96)}…`}</CodeBlock>
        </div>
      );
    }
    if (step.id === 2) return <CodeBlock title="Request URL (GET /escrow/{service_hash})">{`/escrow/${escrowHash || serviceHash}`}</CodeBlock>;
    if (step.id === 3) return <CodeBlock title="Request Body (POST /release)">{JSON.stringify({ service_hash: escrowHash || serviceHash }, null, 2)}</CodeBlock>;
    return <CodeBlock title="Request URL (GET /reputation/{agent})">{`/reputation/${examplePayee}`}</CodeBlock>;
  };

  return (
    <div className="space-y-6">
      <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4 text-sm text-blue-100 leading-relaxed">
        The hosted demo sends a labelled x402-style <span className="font-mono">X-Payment</span> identity header so the live backend can identify the sender without a wallet popup. In production, a wallet/agent signs the same payload with Ed25519 and replay protection.
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_520px] gap-6 items-start">
        <section className="space-y-4">
          <div className="flex flex-wrap gap-3">
            <button onClick={() => runStep(currentStep)} disabled={overallLoading || currentStep >= demoSteps.length || demoSteps[currentStep]?.disabled} className="flex items-center px-6 py-3 bg-amber-600 hover:bg-amber-700 text-white font-semibold rounded-lg shadow-md transition-colors duration-200 disabled:opacity-50 disabled:cursor-not-allowed">
              {overallLoading ? <Loader2 className="animate-spin h-5 w-5 mr-2" /> : <Play className="h-5 w-5 mr-2" />}
              {currentStep < demoSteps.length ? `Run Step ${currentStep + 1}` : 'Demo Complete'}
            </button>
            <button onClick={resetDemo} className="flex items-center px-6 py-3 bg-gray-700 hover:bg-gray-600 text-gray-200 font-semibold rounded-lg shadow-md transition-colors duration-200">
              <RefreshCw className="h-5 w-5 mr-2" /> Reset Demo
            </button>
          </div>

          {overallError && (
            <div className="text-red-500 bg-red-900/20 border border-red-700 rounded-lg p-4 flex items-center"><XCircle className="h-6 w-6 mr-2" /><p>Overall Demo Error: {overallError}</p></div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {demoSteps.map((step, index) => (
              <div key={step.id} className={`bg-[#12121a] border ${step.status === 'success' ? 'border-green-500/70' : step.status === 'error' ? 'border-red-500/70' : step.status === 'loading' ? 'border-amber-500 animate-pulse' : index === currentStep ? 'border-amber-500/40' : 'border-[#1e1e2e]'} rounded-lg p-5 shadow-md`}>
                <div className="flex items-start gap-3">
                  <div className={`rounded-full p-2 ${getStatusColor(step.status)} bg-gray-800 shrink-0`}>{step.status === 'loading' ? <Loader2 className="animate-spin h-5 w-5" /> : <step.icon className="h-5 w-5" />}</div>
                  <div>
                    <h3 className="text-lg font-semibold text-gray-50">Step {step.id}: {step.name}</h3>
                    <p className="text-sm text-gray-400 mt-1">{step.description}</p>
                    <p className="text-xs text-gray-500 mt-3">Status: <span className="font-mono">{step.status}</span></p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>

        <aside className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-6 space-y-4 xl:sticky xl:top-32">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-xl font-semibold text-gray-50">Current request & result</h3>
            {displayStep?.status === 'success' && <CheckCircle className="h-5 w-5 text-green-400" />}
            {displayStep?.status === 'error' && <XCircle className="h-5 w-5 text-red-400" />}
          </div>
          <p className="text-sm text-gray-400">Showing step {displayStep?.id}: {displayStep?.name}. The response stays pinned here after each action.</p>
          {renderRequestPreview(displayStep)}
          <div>
            <p className="text-gray-300 font-medium mb-2">API response</p>
            {displayStep?.response ? (
              <CodeBlock>{JSON.stringify(displayStep.response, null, 2)}</CodeBlock>
            ) : displayStep?.status === 'loading' ? (
              <div className="flex items-center text-amber-300"><Loader2 className="animate-spin h-5 w-5 mr-2" /> Waiting for backend…</div>
            ) : (
              <div className="bg-gray-800 rounded-md p-4 text-sm text-gray-500">Run the next step to see the live response here.</div>
            )}
            {(displayStep?.response?.mlkem_algorithm || displayStep?.response?.mlkem_ciphertext) && (
              <div className="mt-3 bg-purple-500/10 border border-purple-500/30 rounded-lg p-3 text-sm text-purple-100">
                ML-KEM metadata encryption visible: <span className="font-mono">{displayStep.response.mlkem_algorithm || 'ML-KEM-768'}</span>
                {displayStep.response?.mlkem_ciphertext && <span className="block break-all font-mono">{displayStep.response.mlkem_ciphertext}</span>}
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
};

export default AgentDemo;
