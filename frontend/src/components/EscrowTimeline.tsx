import React, { useState, useEffect } from 'react';

// Define types for escrow status and props
enum EscrowStatus {
  Created = 'Created',
  Funded = 'Funded',
  InProgress = 'InProgress',
  Completed = 'Completed',
  Disputed = 'Disputed',
}

interface EscrowTimelineProps {
  escrowId: string;
  currentStatus: EscrowStatus;
  paymentProgress: number; // 0-100, for InProgress status
  lastUpdate: string; // ISO string date
}

const statusOrder = [
  EscrowStatus.Created,
  EscrowStatus.Funded,
  EscrowStatus.InProgress,
  EscrowStatus.Completed,
];

const EscrowTimeline: React.FC<EscrowTimelineProps> = ({
  escrowId,
  currentStatus,
  paymentProgress,
  lastUpdate,
}) => {
  const [internalStatus, setInternalStatus] = useState<EscrowStatus>(currentStatus);
  const [internalPaymentProgress, setInternalPaymentProgress] = useState<number>(paymentProgress);

  useEffect(() => {
    // Update internal state when props change, allowing for CSS transitions
    setInternalStatus(currentStatus);
    setInternalPaymentProgress(paymentProgress);
  }, [currentStatus, paymentProgress]);

  const getStatusIndex = (status: EscrowStatus) => {
    if (status === EscrowStatus.Disputed) {
      // Disputed is a special state, not part of the linear progression
      return -1;
    }
    return statusOrder.indexOf(status);
  };

  const currentStatusIndex = getStatusIndex(internalStatus);
  const isDisputed = internalStatus === EscrowStatus.Disputed;

  return (
    <div className="p-6 bg-gray-900 text-gray-100 rounded-lg shadow-xl max-w-4xl mx-auto my-8">
      <h2 className="text-2xl font-bold mb-6 text-center text-blue-400">Escrow Lifecycle: {escrowId}</h2>

      <div className="relative flex justify-between items-center mb-8">
        {/* Timeline line */}
        <div className="absolute left-0 right-0 h-1 bg-gray-700 rounded-full mx-6">
          <div
            className="h-full bg-blue-500 rounded-full transition-all duration-700 ease-in-out"
            style={{
              width: `${Math.max(0, (currentStatusIndex / (statusOrder.length - 1)) * 100)}%`
            }}
          ></div>
        </div>

        {statusOrder.map((status, index) => {
          const isActive = index <= currentStatusIndex;
          const isCurrent = index === currentStatusIndex;
          const isCompleted = currentStatus === EscrowStatus.Completed && index === statusOrder.length -1;
          const isPast = index < currentStatusIndex;

          return (
            <div key={status} className="flex flex-col items-center z-10 w-1/4">
              <div
                className={`
                  w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold
                  transition-all duration-500 ease-in-out
                  ${isCompleted ? 'bg-green-500 text-white' :
                    isCurrent && !isDisputed ? 'bg-blue-500 text-white scale-110' :
                    isActive ? 'bg-blue-700 text-white' :
                    'bg-gray-600 text-gray-300'}
                `}
              >
                {isCompleted ? '✓' : index + 1}
              </div>
              <p className={`mt-2 text-xs sm:text-sm text-center font-medium
                ${isCurrent && !isDisputed ? 'text-blue-300 font-semibold' :
                  isPast ? 'text-gray-400' : 'text-gray-500'}
              `}>
                {status}
              </p>
            </div>
          );
        })}
      </div>

      {isDisputed && (
        <div className="bg-red-800 border border-red-600 p-4 rounded-md text-center mb-6 animate-pulse">
          <p className="text-lg font-semibold text-red-100">Escrow is currently <span className="uppercase">{EscrowStatus.Disputed}</span>!</p>
          <p className="text-sm text-red-200">Arbitration process initiated. Last update: {new Date(lastUpdate).toLocaleString()}</p>
        </div>
      )}

      {internalStatus === EscrowStatus.InProgress && (
        <div className="mt-8">
          <h3 className="text-xl font-semibold mb-3 text-blue-300">Payment Streaming Progress</h3>
          <div className="w-full bg-gray-700 rounded-full h-4 relative overflow-hidden">
            <div
              className="bg-green-500 h-full rounded-full transition-all duration-1000 ease-out"
              style={{ width: `${internalPaymentProgress}%` }}
            ></div>
            <span className="absolute inset-0 flex items-center justify-center text-xs font-bold text-white">
              {internalPaymentProgress.toFixed(0)}% Complete
            </span>
          </div>
          <p className="text-sm text-gray-400 mt-2 text-right">Last updated: {new Date(lastUpdate).toLocaleString()}</p>
        </div>
      )}

      {internalStatus === EscrowStatus.Completed && (
        <div className="bg-green-800 border border-green-600 p-4 rounded-md text-center mt-8">
          <p className="text-lg font-semibold text-green-100">Escrow <span className="uppercase">{EscrowStatus.Completed}</span>!</p>
          <p className="text-sm text-green-200">All funds released. Last update: {new Date(lastUpdate).toLocaleString()}</p>
        </div>
      )}

      {internalStatus === EscrowStatus.Created && (
        <div className="bg-gray-800 border border-gray-700 p-4 rounded-md text-center mt-8">
          <p className="text-lg font-semibold text-gray-100">Escrow <span className="uppercase">{EscrowStatus.Created}</span>.</p>
          <p className="text-sm text-gray-400">Waiting for client to fund the escrow. Last update: {new Date(lastUpdate).toLocaleString()}</p>
        </div>
      )}

      {internalStatus === EscrowStatus.Funded && (
        <div className="bg-yellow-800 border border-yellow-600 p-4 rounded-md text-center mt-8">
          <p className="text-lg font-semibold text-yellow-100">Escrow <span className="uppercase">{EscrowStatus.Funded}</span>.</p>
          <p className="text-sm text-yellow-200">Waiting for agent to start work. Last update: {new Date(lastUpdate).toLocaleString()}</p>
        </div>
      )}
    </div>
  );
};

export default EscrowTimeline;

// Example Usage (for testing/demo purposes)
/*
function App() {
  const [status, setStatus] = useState<EscrowStatus>(EscrowStatus.Created);
  const [progress, setProgress] = useState(0);
  const [lastUpdate, setLastUpdate] = useState(new Date().toISOString());

  useEffect(() => {
    const interval = setInterval(() => {
      setLastUpdate(new Date().toISOString());
      if (status === EscrowStatus.InProgress) {
        setProgress(prev => Math.min(100, prev + 10));
        if (progress >= 100) {
          setStatus(EscrowStatus.Completed);
          clearInterval(interval);
        }
      }
    }, 2000); // Simulate progress every 2 seconds

    return () => clearInterval(interval);
  }, [status, progress]);

  const handleNextStatus = () => {
    setLastUpdate(new Date().toISOString());
    if (status === EscrowStatus.Created) setStatus(EscrowStatus.Funded);
    else if (status === EscrowStatus.Funded) setStatus(EscrowStatus.InProgress);
    else if (status === EscrowStatus.InProgress && progress < 100) setProgress(100); // Force complete
    else if (status === EscrowStatus.InProgress && progress >= 100) setStatus(EscrowStatus.Completed);
    else if (status === EscrowStatus.Completed) setStatus(EscrowStatus.Disputed); // Can dispute even after complete for a period
    else if (status === EscrowStatus.Disputed) setStatus(EscrowStatus.Created); // Reset for demo
  };

  return (
    <div className="bg-gray-950 min-h-screen flex flex-col items-center justify-center">
      <EscrowTimeline
        escrowId="escrow-xyz-123"
        currentStatus={status}
        paymentProgress={progress}
        lastUpdate={lastUpdate}
      />
      <button
        onClick={handleNextStatus}
        className="mt-8 px-6 py-3 bg-purple-600 hover:bg-purple-700 text-white rounded-md font-semibold transition-colors duration-200"
      >
        Advance Status (Demo)
      </button>
    </div>
  );
}
*/
