import { useEffect, useRef, useState } from 'react';

const BASE_URL = '/backend';

export interface EscrowEvent {
  type: 'escrow_created' | 'escrow_released' | 'escrow_disputed' | 'connected';
  service_hash?: string;
  ts: number;
}

/**
 * React hook that subscribes to the backend SSE stream (`GET /events`)
 * and fires `onEvent` for every escrow lifecycle event.
 *
 * Reconnects automatically with exponential backoff (max 30 s).
 * Returns `{ connected }` so the UI can show a live-indicator dot.
 */
export function useEscrowEvents(onEvent: (event: EscrowEvent) => void): { connected: boolean } {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let es: EventSource | null = null;
    let retryDelay = 1000;
    let unmounted = false;

    function connect() {
      if (unmounted) return;
      es = new EventSource(`${BASE_URL}/events`);

      es.onmessage = (msg) => {
        try {
          const event: EscrowEvent = JSON.parse(msg.data);
          if (event.type === 'connected') {
            setConnected(true);
            retryDelay = 1000;
            return;
          }
          onEventRef.current(event);
        } catch {
          // ignore malformed
        }
      };

      es.onerror = () => {
        setConnected(false);
        es?.close();
        if (!unmounted) {
          setTimeout(connect, retryDelay);
          retryDelay = Math.min(retryDelay * 2, 30000);
        }
      };
    }

    connect();
    return () => {
      unmounted = true;
      es?.close();
    };
  }, []);

  return { connected };
}
