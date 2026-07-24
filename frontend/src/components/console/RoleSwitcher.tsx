/**
 * RoleSwitcher — the segmented control that flips console mode between
 * Observer (read-only, default for a first-time visitor) and Driver
 * (full write authority).
 *
 * Sits in the console top bar next to the wallet indicator so a
 * reviewer/regulator sees at a glance whether the current session is
 * capable of writing to the shared testnet backend. See `lib/role.tsx`
 * for the contract and persistence rules.
 */
import { useCallback } from 'react';
import { Eye, PenSquare, Info } from 'lucide-react';
import { useRole } from '../../lib/role';

interface Props {
  compact?: boolean;
}

const RoleSwitcher: React.FC<Props> = ({ compact = false }) => {
  const { role, setRole } = useRole();

  const toObserver = useCallback(() => setRole('observer'), [setRole]);
  const toDriver = useCallback(() => {
    if (role === 'driver') return;
    // Driver mode enables writes on the shared testnet backend. Make the
    // opt-in explicit for a first-time toggle; a reviewer that lands on the
    // hackathon URL and randomly hits a button shouldn't be able to burn
    // gas or seed junk records without an intentional confirmation.
    const ok = window.confirm(
      'Switch to Driver mode? Driver enables write actions against the shared testnet backend (create/release/refund escrows, register agents, admin operations). Switch only if you intend to act on behalf of a real agent.',
    );
    if (ok) setRole('driver');
  }, [role, setRole]);

  return (
    <div
      role="group"
      aria-label="Console role"
      className={`inline-flex items-center gap-1 rounded-lg border border-ae-border bg-ae-card p-0.5 ${
        compact ? '' : 'shadow-sm'
      }`}
    >
      <button
        type="button"
        onClick={toObserver}
        aria-pressed={role === 'observer'}
        title="Observer — read-only. Backend writes are disabled."
        className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ae-accent-bright ${
          role === 'observer'
            ? 'bg-amber-500/20 text-amber-200 border border-amber-500/40'
            : 'text-gray-400 hover:text-gray-100'
        }`}
      >
        <Eye className="h-3.5 w-3.5" aria-hidden="true" />
        Observer
      </button>
      <button
        type="button"
        onClick={toDriver}
        aria-pressed={role === 'driver'}
        title="Driver — full authority. Backend writes are enabled."
        className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ae-accent-bright ${
          role === 'driver'
            ? 'bg-emerald-500/20 text-emerald-200 border border-emerald-500/40'
            : 'text-gray-400 hover:text-gray-100'
        }`}
      >
        <PenSquare className="h-3.5 w-3.5" aria-hidden="true" />
        Driver
      </button>
      {!compact && (
        <span
          title="Observer = read-only; Driver = writes enabled. Choice is per-browser only, not a backend permission."
          className="ml-0.5 inline-flex h-6 w-6 items-center justify-center text-gray-500 hover:text-gray-300 cursor-help"
          aria-hidden="true"
        >
          <Info className="h-3.5 w-3.5" />
        </span>
      )}
    </div>
  );
};

export default RoleSwitcher;
