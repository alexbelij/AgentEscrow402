/**
 * Role context — Observer vs Driver mode for the AE402 console.
 *
 * Observer  — read-only. Everything that would touch the backend as a WRITE
 *             (POST/PUT/PATCH/DELETE, wallet signature, admin action) is
 *             disabled with an inline hint that the role is Observer.
 *             Regulators / auditors / hackathon judges / external reviewers
 *             use this so they can walk the lifecycle without risking state
 *             changes on the shared testnet backend.
 *
 * Driver    — full authority. The default when the user explicitly opts in.
 *             All write actions are enabled; no gating.
 *
 * Persisted per-browser under `ae402_console_role`. The mode never affects
 * the backend or the SSE stream — it is a *frontend policy fence* only. The
 * backend continues to accept whatever a signed wallet is authorised for.
 * Do not treat this as authorisation; it is a UX affordance.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

export type ConsoleRole = 'observer' | 'driver';

const STORAGE_KEY = 'ae402_console_role';
const DEFAULT_ROLE: ConsoleRole = 'observer';

interface RoleContextValue {
  role: ConsoleRole;
  setRole: (role: ConsoleRole) => void;
  isDriver: boolean;
  isObserver: boolean;
  /**
   * The single reason string surfaced everywhere a write action is blocked.
   * Kept in one place so a11y tooltips, disabled buttons and blocking
   * modals stay in lock-step.
   */
  blockedReason: string;
}

const RoleContext = createContext<RoleContextValue | null>(null);

function readInitial(): ConsoleRole {
  if (typeof window === 'undefined') return DEFAULT_ROLE;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === 'observer' || raw === 'driver') return raw;
  } catch {
    /* ignore quota / private-mode errors */
  }
  return DEFAULT_ROLE;
}

export function RoleProvider({ children }: { children: ReactNode }) {
  const [role, setRoleState] = useState<ConsoleRole>(readInitial);

  const setRole = useCallback((next: ConsoleRole) => {
    setRoleState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore */
    }
    // Emit a window event so non-React observers (e.g. dev-console) can log.
    try {
      window.dispatchEvent(
        new CustomEvent('ae402:console:role', { detail: { role: next } }),
      );
    } catch {
      /* ignore */
    }
  }, []);

  // Cross-tab sync — flipping the role in one tab reflects in all others.
  useEffect(() => {
    function onStorage(e: StorageEvent) {
      if (e.key !== STORAGE_KEY) return;
      if (e.newValue === 'observer' || e.newValue === 'driver') {
        setRoleState(e.newValue);
      }
    }
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  // Reflect role as a data-attribute on <html> so CSS + non-React callers
  // (e.g. static onclick handlers left over anywhere) can consult it too.
  useEffect(() => {
    if (typeof document === 'undefined') return;
    document.documentElement.setAttribute('data-console-role', role);
  }, [role]);

  const value = useMemo<RoleContextValue>(
    () => ({
      role,
      setRole,
      isDriver: role === 'driver',
      isObserver: role === 'observer',
      blockedReason:
        'Observer mode is read-only. Switch to Driver in the console header to perform this action.',
    }),
    [role, setRole],
  );

  return <RoleContext.Provider value={value}>{children}</RoleContext.Provider>;
}

export function useRole(): RoleContextValue {
  const ctx = useContext(RoleContext);
  if (!ctx) {
    // Fall back to a safe read-only stub instead of throwing — a component
    // rendered outside the provider (e.g. isolated visual test) should
    // degrade to "observer" instead of blowing up the tree.
    return {
      role: 'observer',
      setRole: () => {},
      isDriver: false,
      isObserver: true,
      blockedReason:
        'Observer mode is read-only. Switch to Driver in the console header to perform this action.',
    };
  }
  return ctx;
}
