import React from 'react';
import { FileText, Link, Code, Info, ExternalLink, Hash } from 'lucide-react';

const CONTRACT_HASH = '5dd33e8e79789d386832a80c39006002383fa44dd76ba677cae3277f3a134451'; // Corrected hash from prompt
const EXPLORER_BASE_URL = 'https://testnet.cspr.live';

const contractFunctions = [
  {
    name: 'create_escrow',
    description: 'Initializes a new escrow. Requires payer, payee, amount, and token contract. An optional arbiter can be specified.',
    params: ['payer: PublicKey', 'payee: PublicKey', 'amount: U512', 'token_contract: ContractHash', 'arbiter?: PublicKey'],
  },
  {
    name: 'fund_escrow',
    description: 'Transfers the specified amount from the payer to the escrow contract. This changes the escrow status to "funded".',
    params: ['escrow_hash: Hash'],
  },
  {
    name: 'release',
    description: 'Releases the escrowed funds to the payee. Can be initiated by the payer or the arbiter (if assigned).',
    params: ['escrow_hash: Hash', 'initiator: PublicKey', 'signature: String'],
  },
  {
    name: 'refund',
    description: 'Refunds the escrowed funds back to the payer. Can be initiated by the payee or the arbiter (if assigned).',
    params: ['escrow_hash: Hash', 'initiator: PublicKey', 'signature: String'],
  },
  {
    name: 'dispute',
    description: 'Initiates a dispute process for an escrow. Typically requires an arbiter to resolve.',
    params: ['escrow_hash: Hash', 'initiator: PublicKey', 'reason: String', 'signature: String'],
  },
  {
    name: 'resolve_dispute',
    description: 'An arbiter resolves a disputed escrow, either releasing funds to payee or refunding to payer.',
    params: ['escrow_hash: Hash', 'arbiter: PublicKey', 'resolution: "release" | "refund"', 'signature: String'],
  },
  {
    name: 'get_escrow',
    description: 'Retrieves the current state of a specific escrow by its hash.',
    params: ['escrow_hash: Hash'],
  },
  {
    name: 'get_reputation',
    description: 'Fetches the reputation score and metrics for a given agent public key.',
    params: ['agent_public_key: PublicKey'],
  },
  {
    name: 'register_identity',
    description: 'Registers a new agent identity with a public key and name.',
    params: ['public_key: PublicKey', 'name: String'],
  },
  // Add more functions as needed based on the protocol's contract
];

const Contracts: React.FC = () => {
  return (
    <div className="space-y-8">
      <h2 className="text-3xl font-bold text-gray-50">Contract Information</h2>

      {/* Main Contract Details */}
      <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-6 shadow-md">
        <h3 className="text-xl font-semibold text-gray-300 mb-4 flex items-center">
          <FileText className="h-6 w-6 mr-2 text-amber-500" />
          AgentEscrow402 Core Contract
        </h3>
        <div className="space-y-3 text-gray-300">
          <p className="flex items-center">
            <Hash className="h-5 w-5 mr-2 text-gray-500" />
            <strong>Contract Hash:</strong>{' '}
            <span className="ml-2 font-mono break-all text-amber-400">{CONTRACT_HASH}</span>
          </p>
          <p className="flex items-center">
            <Link className="h-5 w-5 mr-2 text-gray-500" />
            <strong>Explorer Link:</strong>{' '}
            <a
              href={`${EXPLORER_BASE_URL}/contract/${CONTRACT_HASH}`}
              target="_blank"
              rel="noopener noreferrer"
              className="ml-2 text-blue-400 hover:underline flex items-center"
            >
              View on CSPR.Live <ExternalLink className="h-4 w-4 ml-1" />
            </a>
          </p>
          <p className="flex items-center">
            <Info className="h-5 w-5 mr-2 text-gray-500" />
            <strong>Description:</strong> The core smart contract implementing the AgentEscrow402 protocol,
            managing escrow creation, funding, release, refund, dispute resolution, and agent reputation.
          </p>
        </div>
      </div>

      {/* Key Functions */}
      <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-6 shadow-md">
        <h3 className="text-xl font-semibold text-gray-300 mb-4 flex items-center">
          <Code className="h-6 w-6 mr-2 text-amber-500" />
          Key Contract Functions
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {contractFunctions.map((func, index) => (
            <div key={index} className="bg-gray-800 border border-[#1e1e2e] rounded-lg p-4">
              <h4 className="text-lg font-semibold text-amber-400 mb-2">{func.name}</h4>
              <p className="text-gray-400 text-sm mb-3">{func.description}</p>
              <div className="text-xs text-gray-500">
                <p className="font-medium mb-1">Parameters:</p>
                <ul className="list-disc list-inside space-y-0.5">
                  {func.params.map((param, pIndex) => (
                    <li key={pIndex} className="font-mono">{param}</li>
                  ))}
                </ul>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Additional Contract Info (Placeholder) */}
      <div className="bg-[#12121a] border border-[#1e1e2e] rounded-lg p-6 shadow-md">
        <h3 className="text-xl font-semibold text-gray-300 mb-4 flex items-center">
          <Info className="h-6 w-6 mr-2 text-amber-500" />
          Additional Information
        </h3>
        <p className="text-gray-400">
          For detailed contract source code, ABI, and deployment specifics, please refer to the
          official AgentEscrow402 GitHub repository or the Casper Testnet Explorer link provided above.
          This section will be expanded with more technical details as they become available.
        </p>
      </div>
    </div>
  );
};

export default Contracts;
