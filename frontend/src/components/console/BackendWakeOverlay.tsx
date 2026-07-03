import React, { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';

/**
 * Global, non-blocking preloader. The API layer dispatches `backend:state`
 * events ('waking' | 'ready') while it retries requests against a cold /
 * restarting free-tier backend. Instead of pages crashing with "Failed to
 * fetch", the user sees a friendly "waking up" banner and the request
 * completes automatically once the server responds.
 */
const BackendWakeOverlay: React.FC = () => {
  const [waking, setWaking] = useState(false);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    let active = 0; // reference count of in-flight waking requests
    const onState = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail === 'waking') active += 1;
      else if (detail === 'ready') active = Math.max(0, active - 1);
      setWaking(active > 0);
    };
    window.addEventListener('backend:state', onState as EventListener);
    return () => window.removeEventListener('backend:state', onState as EventListener);
  }, []);

  useEffect(() => {
    if (!waking) { setElapsed(0); return; }
    const t = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [waking]);

  if (!waking) return null;

  return (
    <div className="fixed bottom-4 right-4 z-[60] max-w-sm">
      <div className="flex items-start gap-3 rounded-xl border border-amber-600/40 bg-[#12121a] px-4 py-3 shadow-2xl">
        <Loader2 className="mt-0.5 h-5 w-5 animate-spin text-amber-500" />
        <div>
          <p className="text-sm font-semibold text-gray-100">Connecting to backend…</p>
          <p className="text-xs text-gray-400">
            The free-tier server may be waking from sleep. Retrying automatically
            {elapsed > 2 ? ` (${elapsed}s)` : ''} — no need to refresh.
          </p>
        </div>
      </div>
    </div>
  );
};

export default BackendWakeOverlay;
