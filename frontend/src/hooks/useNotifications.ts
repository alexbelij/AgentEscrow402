/**
 * useNotifications — subscribes to the backend SSE stream (GET /events) and
 * fires a toast for every user-facing escrow lifecycle event.
 *
 * Contract: AE402_AGENT_SPEC.md batch-2 A5. Event types emitted server-side:
 *   - escrow_created
 *   - escrow_released
 *   - dispute_opened            (alias of escrow_disputed)
 *   - arbitration_complete      (alias of escrow_resolved)
 *   - insurance_claimed
 *
 * The `escrow_*` names are also broadcast by the backend for older consumers
 * (see `frontend/src/lib/useEscrowEvents.ts`), but this hook intentionally
 * listens only to the spec-named aliases so a page mounting *both* hooks does
 * not get two toasts per event.
 */
import { useEffect } from 'react';
import { useToast } from '../lib/toast';

type NotificationType =
  | 'escrow_created'
  | 'escrow_released'
  | 'dispute_opened'
  | 'arbitration_complete'
  | 'insurance_claimed'
  | 'connected';

interface NotificationEvent {
  type: NotificationType;
  service_hash?: string;
  escrow_hash?: string;
  amount?: number;
  ts: number;
}

const SSE_URL = '/backend/events';

function shortHash(hash: string | undefined): string {
  if (!hash) return '';
  return hash.length > 12 ? `${hash.slice(0, 8)}…${hash.slice(-4)}` : hash;
}

function messageFor(event: NotificationEvent): { kind: 'success' | 'error' | 'info'; text: string } | null {
  const short = shortHash(event.service_hash || event.escrow_hash);
  switch (event.type) {
    case 'escrow_created':
      return { kind: 'info', text: `Escrow created: ${short}` };
    case 'escrow_released':
      return { kind: 'success', text: `Escrow released: ${short}` };
    case 'dispute_opened':
      return { kind: 'error', text: `Dispute opened: ${short}` };
    case 'arbitration_complete':
      return { kind: 'success', text: `Arbitration complete: ${short}` };
    case 'insurance_claimed':
      return { kind: 'success', text: `Insurance claim paid: ${short}` };
    default:
      return null;
  }
}

/**
 * Mount once, near the top of the console tree, inside a `ToastProvider`.
 * Reconnects with exponential backoff (max 30 s) — same shape as
 * `useEscrowEvents`, kept independent so the two hooks can coexist without
 * one refactor breaking the other.
 */
export function useNotifications(): void {
  const toast = useToast();

  useEffect(() => {
    let es: EventSource | null = null;
    let retryDelay = 1000;
    let unmounted = false;

    function connect() {
      if (unmounted) return;
      es = new EventSource(SSE_URL);

      es.onmessage = (msg) => {
        try {
          const event = JSON.parse(msg.data) as NotificationEvent;
          if (event.type === 'connected') {
            retryDelay = 1000;
            return;
          }
          const notification = messageFor(event);
          if (!notification) return;
          if (notification.kind === 'success') toast.success(notification.text);
          else if (notification.kind === 'error') toast.error(notification.text);
          else toast.info(notification.text);
        } catch {
          // ignore malformed frames
        }
      };

      es.onerror = () => {
        es?.close();
        if (unmounted) return;
        window.setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 30_000);
      };
    }

    connect();
    return () => {
      unmounted = true;
      es?.close();
    };
    // toast is a stable ref from context; safe to depend on it
  }, [toast]);
}
