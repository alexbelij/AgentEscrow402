import React, { useState, useEffect } from 'react';
import { api, CreateEscrowRequest, EscrowActionRequest } from '../../lib/api';
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
  const [serviceHash] = useState<string>(randomHex64());

  const examplePayee = '01fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210'; // demo receiver
  const exampleAmountCspr = 100; // 100 CSPR -> converted to motes below

  const resetDemo = () => {
    setCurrentStep(0);
    setEscrowHash(null);
    setOverallLoading(false);
    setOverallError(null);
    initializeSteps();
  };

  const initializeSteps = () => {
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
            service_hash: serviceHash,
            ttl: 300,
          };
          const res = await api.createEscrow(req);
          // The escrow is addressed by its service_hash for all later actions.
          if (res.data && !res.error) {
            setEscrowHash((res.data as any).service_hash || serviceHash);
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
          if (!escrowHash) throw new Error('Escrow hash not available. Complete Step 1 first.');
          return await api.getEscrowByHash(escrowHash);
        },
        disabled: !escrowHash,
      },
      {
        id: 3,
        name: 'Release Escrow',
        description: 'Upon service completion, the Payer (or Arbiter) releases funds to the Payee.',
        icon: Send,
        status: 'pending',
        response: null,
        action: async () => {
          if (!escrowHash) throw new Error('Escrow hash not available. Complete Step 1 first.');
          const req: EscrowActionRequest = { service_hash: escrowHash };
          return await api.releaseEscrow(req);
        },
        disabled: !escrowHash,
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
  }, [escrowHash]); // Re-initialize if escrowHash changes (e.g., after step 1 completes)

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

  return (
    <div className="space-y-8">
      <h2 className="text-3xl font-bold text-gray-50">Agent Escrow Demo</h2>
      <p className="text-gray-400">
        Walk through a typical escrow lifecycle for AI agents on the Casper blockchain.
        This demo uses placeholder public keys and a mock signature for illustrative purposes.
      </p>

      <div className="flex gap-4">
        <button
          onClick={() => runStep(currentStep)}
          disabled={overallLoading || currentStep >= demoSteps.length || demoSteps[currentStep]?.disabled}
          className="flex items-center px-6 py-3 bg-amber-600 hover:bg-amber-700 text-white font-semibold rounded-lg shadow-md transition-colors duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {overallLoading ? <Loader2 className="animate-spin h-5 w-5 mr-2" /> : <Play className="h-5 w-5 mr-2" />}
          {currentStep < demoSteps.length ? `Run Step ${currentStep + 1}` : 'Demo Complete'}
        </button>
        <button
          onClick={resetDemo}
          className="flex items-center px-6 py-3 bg-gray-700 hover:bg-gray-600 text-gray-200 font-semibold rounded-lg shadow-md transition-colors duration-200"
        >
          <RefreshCw className="h-5 w-5 mr-2" />
          Reset Demo
        </button>
      </div>

      {overallError && (
        <div className="text-red-500 bg-red-900/20 border border-red-700 rounded-lg p-4 flex items-center">
          <XCircle className="h-6 w-6 mr-2" />
          <p>Overall Demo Error: {overallError}</p>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {demoSteps.map((step, index) => (
          <div
            key={step.id}
            className={`bg-[#12121a] border ${
              step.status === 'success' ? 'border-green-500' :
              step.status === 'error' ? 'border-red-500' :
              step.status === 'loading' ? 'border-amber-500 animate-pulse' :
              'border-[#1e1e2e]'
            } rounded-lg p-6 shadow-md relative`}
          >
            <div className="flex items-center mb-4">
              <div className={`rounded-full p-2 ${getStatusColor(step.status)} bg-gray-800 mr-3`}>
                {step.status === 'loading' ? <Loader2 className="animate-spin h-6 w-6" /> : <step.icon className="h-6 w-6" />}
              </div>
              <h3 className="text-xl font-semibold text-gray-50">
                Step {step.id}: {step.name}
              </h3>
            </div>
            <p className="text-gray-400 mb-4">{step.description}</p>

            {step.id === 1 && (
              <CodeBlock title="Request Body (POST /escrow)">
                {JSON.stringify(
                  {
                    receiver: examplePayee,
                    amount: csprToMotes(exampleAmountCspr),
                    service_hash: serviceHash,
                    ttl: 300,
                  },
                  null,
                  2
                )}
              </CodeBlock>
            )}

            {step.id === 2 && (
              <CodeBlock title="Request URL (GET /escrow/{service_hash})">
                {`/escrow/${escrowHash || serviceHash}`}
              </CodeBlock>
            )}

            {step.id === 3 && (
              <CodeBlock title="Request Body (POST /release)">
                {JSON.stringify(
                  {
                    service_hash: escrowHash || serviceHash,
                  },
                  null,
                  2
                )}
              </CodeBlock>
            )}

            {step.id === 4 && (
              <CodeBlock title="Request URL (GET /reputation/{agent})">
                {`/reputation/${examplePayee}`}
              </CodeBlock>
            )}

            {step.response && (
              <div className="mt-4">
                <p className="text-gray-300 font-medium mb-2 flex items-center">
                  {step.status === 'success' ? (
                    <CheckCircle className="h-5 w-5 text-green-500 mr-2" />
                  ) : (
                    <XCircle className="h-5 w-5 text-red-500 mr-2" />
                  )}
                  API Response:
                </p>
                <CodeBlock>
                  {JSON.stringify(step.response, null, 2)}
                </CodeBlock>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};

export default AgentDemo;
