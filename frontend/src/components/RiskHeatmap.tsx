import React, { useState, useEffect } from 'react';

// Define types for escrow and risk levels
enum RiskLevel {
  Low = 'low',
  Medium = 'medium',
  High = 'high',
}

interface Escrow {
  id: string;
  name: string;
  agentId: string;
  clientId: string;
  amount: number;
  currency: string;
  riskLevel: RiskLevel;
  status: string;
  createdAt: string;
  lastActivity: string;
  details: string;
}

// Mock data for demonstration
const mockEscrows: Escrow[] = [
  {
    id: 'escrow-001', name: 'AI Agent for Data Analysis', agentId: 'agent-alice', clientId: 'client-bob',
    amount: 1500, currency: 'CSPR', riskLevel: RiskLevel.Low, status: 'InProgress',
    createdAt: '2023-10-26T10:00:00Z', lastActivity: '2023-10-27T14:30:00Z',
    details: 'Analyzing market trends for Q4 2023. Payment streaming active.'
  },
  {
    id: 'escrow-002', name: 'Content Generation Service', agentId: 'agent-charlie', clientId: 'client-diana',
    amount: 500, currency: 'CSPR', riskLevel: RiskLevel.Medium, status: 'Funded',
    createdAt: '2023-10-25T11:00:00Z', lastActivity: '2023-10-26T09:00:00Z',
    details: 'Generating 10 blog posts on blockchain technology. Waiting for agent to start.'
  },
  {
    id: 'escrow-003', name: 'Smart Contract Audit', agentId: 'agent-eve', clientId: 'client-frank',
    amount: 5000, currency: 'USDC', riskLevel: RiskLevel.High, status: 'Disputed',
    createdAt: '2023-10-20T09:00:00Z', lastActivity: '2023-10-27T16:00:00Z',
    details: 'Audit of new DeFi protocol. Client claims incomplete work, agent disputes.'
  },
  {
    id: 'escrow-004', name: 'Customer Support AI Integration', agentId: 'agent-grace', clientId: 'client-heidi',
    amount: 2500, currency: 'CSPR', riskLevel: RiskLevel.Low, status: 'Completed',
    createdAt: '2023-10-22T13:00:00Z', lastActivity: '2023-10-26T11:00:00Z',
    details: 'Integrated AI chatbot into existing customer support system. Funds released.'
  },
  {
    id: 'escrow-005', name: 'Predictive Analytics Model', agentId: 'agent-ivan', clientId: 'client-judy',
    amount: 3000, currency: 'CSPR', riskLevel: RiskLevel.Medium, status: 'InProgress',
    createdAt: '2023-10-24T15:00:00Z', lastActivity: '2023-10-27T10:00:00Z',
    details: 'Developing a model to predict stock market fluctuations. Initial data processing done.'
  },
  {
    id: 'escrow-006', name: 'AI Art Generation', agentId: 'agent-karen', clientId: 'client-liam',
    amount: 200, currency: 'CSPR', riskLevel: RiskLevel.Low, status: 'Funded',
    createdAt: '2023-10-27T09:00:00Z', lastActivity: '2023-10-27T09:30:00Z',
    details: 'Generating unique digital art pieces based on client prompts. Agent preparing to start.'
  },
  {
    id: 'escrow-007', name: 'Blockchain Security Review', agentId: 'agent-mike', clientId: 'client-nora',
    amount: 4000, currency: 'USDC', riskLevel: RiskLevel.High, status: 'InProgress',
    createdAt: '2023-10-21T14:00:00Z', lastActivity: '2023-10-27T15:00:00Z',
    details: 'Comprehensive security review of a new Casper dApp. High value, complex task.'
  },
  {
    id: 'escrow-008', name: 'Language Translation Service', agentId: 'agent-olivia', clientId: 'client-peter',
    amount: 750, currency: 'CSPR', riskLevel: RiskLevel.Low, status: 'InProgress',
    createdAt: '2023-10-26T16:00:00Z', lastActivity: '2023-10-27T11:00:00Z',
    details: 'Translating technical documentation from English to Japanese.'
  },
];

const RiskHeatmap: React.FC = () => {
  const [escrows, setEscrows] = useState<Escrow[]>([]);
  const [selectedEscrow, setSelectedEscrow] = useState<Escrow | null>(null);

  useEffect(() => {
    // In a real application, you would fetch data here
    setEscrows(mockEscrows);
  }, []);

  const getRiskColorClass = (riskLevel: RiskLevel): string => {
    switch (riskLevel) {
      case RiskLevel.Low:
        return 'bg-green-500 hover:bg-green-600';
      case RiskLevel.Medium:
        return 'bg-yellow-500 hover:bg-yellow-600';
      case RiskLevel.High:
        return 'bg-red-500 hover:bg-red-600';
      default:
        return 'bg-gray-400 hover:bg-gray-500';
    }
  };

  return (
    <div className="p-6 bg-gray-900 text-gray-100 min-h-screen" role="main" aria-label="Escrow Risk Heatmap Dashboard">
      <h2 className="text-3xl font-bold mb-8 text-center text-blue-400">Active Escrow Risk Heatmap</h2>

      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 mb-8" role="list" aria-label="Escrow risk items">
        {escrows.map((escrow) => (
          <div
            key={escrow.id}
            className={`
              p-4 rounded-lg shadow-md cursor-pointer transition-all duration-200
              flex flex-col justify-between
              ${getRiskColorClass(escrow.riskLevel)}
              ${selectedEscrow?.id === escrow.id ? 'ring-4 ring-blue-300 scale-105' : ''}
            `}
            onClick={() => setSelectedEscrow(escrow)}
          >
            <div>
              <h3 className="text-lg font-semibold truncate">{escrow.name}</h3>
              <p className="text-sm text-gray-200">ID: {escrow.id}</p>
              <p className="text-sm text-gray-200">Agent: {escrow.agentId}</p>
              <p className="text-sm text-gray-200">Client: {escrow.clientId}</p>
              <p className="text-sm font-medium mt-2">
                Amount: {escrow.amount} {escrow.currency}
              </p>
            </div>
            <div className="mt-3 text-right">
              <span className={`inline-block px-3 py-1 text-xs font-semibold rounded-full
                ${escrow.riskLevel === RiskLevel.Low ? 'bg-green-700' :
                  escrow.riskLevel === RiskLevel.Medium ? 'bg-yellow-700' : 'bg-red-700'}
              `}>
                Risk: {escrow.riskLevel.charAt(0).toUpperCase() + escrow.riskLevel.slice(1)}
              </span>
            </div>
          </div>
        ))}
      </div>

      {selectedEscrow && (
        <div className="bg-gray-800 p-6 rounded-lg shadow-xl border border-blue-500">
          <h3 className="text-2xl font-bold mb-4 text-blue-300">Escrow Details: {selectedEscrow.name}</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-gray-200">
            <div>
              <p><strong>Escrow ID:</strong> {selectedEscrow.id}</p>
              <p><strong>Agent ID:</strong> {selectedEscrow.agentId}</p>
              <p><strong>Client ID:</strong> {selectedEscrow.clientId}</p>
              <p><strong>Amount:</strong> {selectedEscrow.amount} {selectedEscrow.currency}</p>
              <p><strong>Status:</strong> <span className="font-semibold text-blue-300">{selectedEscrow.status}</span></p>
            </div>
            <div>
              <p><strong>Risk Level:</strong>
                <span className={`ml-2 px-2 py-1 text-xs font-semibold rounded-full
                  ${selectedEscrow.riskLevel === RiskLevel.Low ? 'bg-green-700' :
                    selectedEscrow.riskLevel === RiskLevel.Medium ? 'bg-yellow-700' : 'bg-red-700'}
                `}>
                  {selectedEscrow.riskLevel.charAt(0).toUpperCase() + selectedEscrow.riskLevel.slice(1)}
                </span>
              </p>
              <p><strong>Created At:</strong> {new Date(selectedEscrow.createdAt).toLocaleString()}</p>
              <p><strong>Last Activity:</strong> {new Date(selectedEscrow.lastActivity).toLocaleString()}</p>
            </div>
            <div className="md:col-span-2 mt-4">
              <p className="font-semibold text-blue-300">Description:</p>
              <p className="bg-gray-700 p-3 rounded-md text-sm">{selectedEscrow.details}</p>
            </div>
          </div>
          <button
            onClick={() => setSelectedEscrow(null)}
            className="mt-6 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-md transition-colors duration-200"
          >
            Close Details
          </button>
        </div>
      )}
    </div>
  );
};

export default RiskHeatmap;
