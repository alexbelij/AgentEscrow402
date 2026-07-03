import React, { useState, useEffect, useMemo } from 'react';

// Define types for Agent
interface Agent {
  id: string;
  name: string;
  identity: {
    publicKey: string;
    description: string;
  };
  reputationScore: number; // 0-100
  trustScore: number; // Derived, 0-100
  capabilities: string[];
  hourlyRate: number;
  currency: string;
  status: 'Available' | 'Busy' | 'Offline';
}

// Mock data for demonstration
const mockAgents: Agent[] = [
  {
    id: 'agent-alice',
    name: 'Alice AI',
    identity: {
      publicKey: '01a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1',
      description: 'Expert in data analysis and predictive modeling for financial markets.',
    },
    reputationScore: 95,
    trustScore: 92,
    capabilities: ['Data Analysis', 'Predictive Modeling', 'Financial Forecasting', 'Python'],
    hourlyRate: 50,
    currency: 'CSPR',
    status: 'Available',
  },
  {
    id: 'agent-bob',
    name: 'Bob ContentBot',
    identity: {
      publicKey: '02b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1',
      description: 'Specializes in generating high-quality blog posts, articles, and marketing copy.',
    },
    reputationScore: 88,
    trustScore: 85,
    capabilities: ['Content Generation', 'SEO Optimization', 'Copywriting', 'Creative Writing'],
    hourlyRate: 30,
    currency: 'CSPR',
    status: 'Busy',
  },
  {
    id: 'agent-charlie',
    name: 'Charlie CodeGuard',
    identity: {
      publicKey: '03c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1',
      description: 'Audits smart contracts for vulnerabilities and provides security recommendations.',
    },
    reputationScore: 98,
    trustScore: 97,
    capabilities: ['Smart Contract Audit', 'Security Analysis', 'Solidity', 'Casper CLVM'],
    hourlyRate: 120,
    currency: 'USDC',
    status: 'Available',
  },
  {
    id: 'agent-diana',
    name: 'Diana DesignAI',
    identity: {
      publicKey: '04d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1',
      description: 'Generates unique visual assets and designs based on textual descriptions.',
    },
    reputationScore: 82,
    trustScore: 80,
    capabilities: ['AI Art Generation', 'Graphic Design', 'Image Synthesis', 'UI/UX Prototyping'],
    hourlyRate: 40,
    currency: 'CSPR',
    status: 'Available',
  },
  {
    id: 'agent-eve',
    name: 'Eve Translator',
    identity: {
      publicKey: '05e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1',
      description: 'Provides accurate and context-aware translations across multiple languages.',
    },
    reputationScore: 90,
    trustScore: 89,
    capabilities: ['Language Translation', 'Natural Language Processing', 'Multilingual Support'],
    hourlyRate: 35,
    currency: 'CSPR',
    status: 'Available',
  },
  {
    id: 'agent-frank',
    name: 'Frank SupportBot',
    identity: {
      publicKey: '06f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1',
      description: 'Integrates into customer support systems to handle queries and provide assistance.',
    },
    reputationScore: 85,
    trustScore: 83,
    capabilities: ['Customer Support', 'Chatbot Development', 'FAQ Automation', 'Sentiment Analysis'],
    hourlyRate: 45,
    currency: 'CSPR',
    status: 'Offline',
  },
];

const allCapabilities = Array.from(new Set(mockAgents.flatMap(agent => agent.capabilities))).sort();

const AgentMarketplace: React.FC = () => {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [selectedCapabilities, setSelectedCapabilities] = useState<string[]>([]);
  const [sortBy, setSortBy] = useState<'trustScore' | 'hourlyRate' | 'name'>('trustScore');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');

  useEffect(() => {
    // In a real application, fetch agents from an API
    setAgents(mockAgents);
  }, []);

  const filteredAndSortedAgents = useMemo(() => {
    let filtered = agents.filter(agent =>
      agent.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      agent.identity.description.toLowerCase().includes(searchTerm.toLowerCase()) ||
      agent.capabilities.some(cap => cap.toLowerCase().includes(searchTerm.toLowerCase()))
    );

    if (selectedCapabilities.length > 0) {
      filtered = filtered.filter(agent =>
        selectedCapabilities.every(cap => agent.capabilities.includes(cap))
      );
    }

    return filtered.sort((a, b) => {
      let comparison = 0;
      if (sortBy === 'trustScore') {
        comparison = a.trustScore - b.trustScore;
      } else if (sortBy === 'hourlyRate') {
        comparison = a.hourlyRate - b.hourlyRate;
      } else if (sortBy === 'name') {
        comparison = a.name.localeCompare(b.name);
      }
      return sortOrder === 'asc' ? comparison : -comparison;
    });
  }, [agents, searchTerm, selectedCapabilities, sortBy, sortOrder]);

  const handleCapabilityChange = (capability: string) => {
    setSelectedCapabilities(prev =>
      prev.includes(capability)
        ? prev.filter(c => c !== capability)
        : [...prev, capability]
    );
  };

  const handleHireAgent = (agentId: string) => {
    console.log(`Hiring agent: ${agentId}`);
    alert(`Initiating escrow for ${agentId}. (This is a demo action)`);
    // In a real app, this would navigate to an escrow creation form or open a modal.
  };

  return (
    <div className="p-6 bg-gray-900 text-gray-100 min-h-screen">
      <h2 className="text-3xl font-bold mb-8 text-center text-blue-400">AI Agent Marketplace</h2>

      <div className="mb-8 grid grid-cols-1 md:grid-cols-3 gap-4">
        <input
          type="text"
          placeholder="Search agents by name, description, or capability..."
          className="p-3 rounded-md bg-gray-800 border border-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 text-gray-100 md:col-span-2"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
        />

        <div className="flex items-center space-x-2">
          <label htmlFor="sortBy" className="text-gray-300">Sort by:</label>
          <select
            id="sortBy"
            className="p-3 rounded-md bg-gray-800 border border-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 text-gray-100"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as 'trustScore' | 'hourlyRate' | 'name')}
          >
            <option value="trustScore">Trust Score</option>
            <option value="hourlyRate">Hourly Rate</option>
            <option value="name">Name</option>
          </select>
          <button
            onClick={() => setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')}
            className="p-3 rounded-md bg-gray-800 border border-gray-700 hover:bg-gray-700 transition-colors duration-200"
          >
            {sortOrder === 'asc' ? '↑ Asc' : '↓ Desc'}
          </button>
        </div>
      </div>

      <div className="mb-8">
        <h3 className="text-xl font-semibold mb-3 text-blue-300">Filter by Capabilities:</h3>
        <div className="flex flex-wrap gap-2">
          {allCapabilities.map(cap => (
            <button
              key={cap}
              onClick={() => handleCapabilityChange(cap)}
              className={`
                px-4 py-2 rounded-full text-sm font-medium transition-colors duration-200
                ${selectedCapabilities.includes(cap)
                  ? 'bg-blue-600 text-white hover:bg-blue-700'
                  : 'bg-gray-700 text-gray-300 hover:bg-gray-600'}
              `}
            >
              {cap}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {filteredAndSortedAgents.length === 0 ? (
          <p className="text-center text-gray-400 md:col-span-3">No agents found matching your criteria.</p>
        ) : (
          filteredAndSortedAgents.map((agent) => (
            <div key={agent.id} className="bg-gray-800 rounded-lg shadow-lg p-6 border border-gray-700 hover:border-blue-500 transition-all duration-200">
              <div className="flex items-center mb-4">
                <div className="w-12 h-12 bg-blue-600 rounded-full flex items-center justify-center text-xl font-bold text-white mr-4">
                  {agent.name.charAt(0)}
                </div>
                <div>
                  <h3 className="text-xl font-bold text-blue-300">{agent.name}</h3>
                  <p className="text-sm text-gray-400">ID: {agent.id}</p>
                </div>
              </div>

              <p className="text-gray-300 mb-4 text-sm">{agent.identity.description}</p>

              <div className="mb-4">
                <p className="text-sm"><strong>Trust Score:</strong> <span className="font-semibold text-green-400">{agent.trustScore}/100</span></p>
                <p className="text-sm"><strong>Reputation:</strong> {agent.reputationScore}/100</p>
                <p className="text-sm"><strong>Hourly Rate:</strong> {agent.hourlyRate} {agent.currency}</p>
                <p className="text-sm"><strong>Status:</strong>
                  <span className={`ml-1 px-2 py-0.5 rounded-full text-xs font-semibold
                    ${agent.status === 'Available' ? 'bg-green-600 text-white' :
                      agent.status === 'Busy' ? 'bg-yellow-600 text-white' :
                      'bg-red-600 text-white'}
                  `}>
                    {agent.status}
                  </span>
                </p>
              </div>

              <div className="mb-4">
                <p className="font-semibold text-blue-300 text-sm mb-2">Capabilities:</p>
                <div className="flex flex-wrap gap-1">
                  {agent.capabilities.map(cap => (
                    <span key={cap} className="bg-gray-700 text-gray-300 px-2 py-1 rounded-full text-xs">
                      {cap}
                    </span>
                  ))}
                </div>
              </div>

              <button
                onClick={() => handleHireAgent(agent.id)}
                className="w-full mt-4 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-md transition-colors duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
                disabled={agent.status !== 'Available'}
              >
                Hire Agent
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default AgentMarketplace;
