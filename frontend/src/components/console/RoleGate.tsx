/**
 * RoleGate — the single frontend fence used by every write action.
 *
 * Wrap any button, form, or block that mutates state:
 *
 *   <RoleGate>
 *     <button onClick={releaseEscrow}>Release</button>
 *   </RoleGate>
 *
 * When the console is in Observer mode:
 *   - `mode="disable"` (default) — the wrapped children are rendered but
 *     wrapped in a `<span aria-disabled>` with `pointer-events: none` and a
 *     reduced opacity, plus a Tailwind `title` tooltip explaining the block.
 *     This preserves layout and screen-reader semantics.
 *   - `mode="hide"` — the wrapped children are not rendered at all. Use for
 *     entire admin panels (e.g. slash-stake) that make no sense to display
 *     to a reviewer.
 *   - `mode="badge"` — renders children plus a small "Observer" pill next
 *     to them for extra clarity on hero CTAs.
 *
 * The gate never renders its own click handler — the wrapped element keeps
 * its own props. In Observer mode, `pointer-events: none` prevents clicks
 * from firing on the underlying element.
 */
import { type ReactNode } from 'react';
import { Eye } from 'lucide-react';
import { useRole } from '../../lib/role';

interface Props {
  children: ReactNode;
  mode?: 'disable' | 'hide' | 'badge';
  /** Optional override for the tooltip text; defaults to `role.blockedReason`. */
  reason?: string;
  className?: string;
}

const RoleGate: React.FC<Props> = ({ children, mode = 'disable', reason, className }) => {
  const { isObserver, blockedReason } = useRole();

  if (!isObserver) {
    return <>{children}</>;
  }

  if (mode === 'hide') return null;

  const tip = reason ?? blockedReason;

  if (mode === 'badge') {
    return (
      <span className={`inline-flex items-center gap-2 ${className ?? ''}`}>
        {children}
        <span
          className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-300"
          title={tip}
        >
          <Eye className="h-3 w-3" aria-hidden="true" /> observer
        </span>
      </span>
    );
  }

  // disable
  return (
    <span
      aria-disabled="true"
      title={tip}
      data-role-blocked="1"
      className={`inline-block cursor-not-allowed opacity-50 [&_button]:pointer-events-none [&_a]:pointer-events-none [&_input]:pointer-events-none [&_select]:pointer-events-none [&_textarea]:pointer-events-none ${className ?? ''}`}
    >
      {children}
    </span>
  );
};

export default RoleGate;
