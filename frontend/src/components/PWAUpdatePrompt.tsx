import { useEffect, useState } from 'react'

/**
 * A tiny, self-contained toast surface for two PWA lifecycle events:
 *   - "update available" — a new service worker is waiting, ask the user
 *     whether to activate it now.
 *   - "offline ready" — first install completed, the console will keep
 *     working without network.
 *
 * Kept in its own component so `App.tsx` only needs to mount it once, and
 * the toast context isn't strictly required (this deliberately uses its
 * own visual so a broken toast provider can't hide these prompts).
 */
export default function PWAUpdatePrompt() {
  const [update, setUpdate] = useState<null | { activate: () => Promise<void> }>(null)
  const [offlineReady, setOfflineReady] = useState(false)

  useEffect(() => {
    function onNeedRefresh(e: Event) {
      const detail = (e as CustomEvent<{ activate: () => Promise<void> }>).detail
      if (detail && typeof detail.activate === 'function') setUpdate({ activate: detail.activate })
    }
    function onOfflineReady() {
      setOfflineReady(true)
      // Auto-dismiss the "offline ready" message after 8s.
      setTimeout(() => setOfflineReady(false), 8000)
    }
    window.addEventListener('ae402:pwa:need-refresh', onNeedRefresh as EventListener)
    window.addEventListener('ae402:pwa:offline-ready', onOfflineReady as EventListener)
    return () => {
      window.removeEventListener('ae402:pwa:need-refresh', onNeedRefresh as EventListener)
      window.removeEventListener('ae402:pwa:offline-ready', onOfflineReady as EventListener)
    }
  }, [])

  if (!update && !offlineReady) return null

  return (
    <div
      style={{
        position: 'fixed',
        // Bottom-right, stacked directly above the scroll-to-top button
        // (ScrollToTop.tsx: `fixed bottom-6 right-6`, 44px tall) with a
        // clear gap so it's never covered by it.
        bottom: '5rem',
        right: '1.5rem',
        zIndex: 9999,
        display: 'flex',
        flexDirection: 'column',
        gap: '0.75rem',
        maxWidth: '340px',
      }}
      role="status"
      aria-live="polite"
    >
      {offlineReady && (
        <div
          style={{
            background: 'rgba(74,222,128,0.10)',
            border: '1px solid rgba(74,222,128,0.45)',
            color: '#e6ffe9',
            padding: '0.75rem 1rem',
            borderRadius: '10px',
            fontSize: '13.5px',
            boxShadow: '0 10px 30px rgba(0,0,0,0.4)',
          }}
        >
          Offline-ready ✅ — the console will keep working without network.
          <button
            type="button"
            onClick={() => setOfflineReady(false)}
            aria-label="Dismiss"
            style={{
              background: 'transparent',
              border: 'none',
              color: '#cbeacd',
              float: 'right',
              cursor: 'pointer',
              fontSize: '16px',
              lineHeight: 1,
              marginLeft: '0.5rem',
            }}
          >
            ×
          </button>
        </div>
      )}
      {update && (
        <div
          style={{
            background: 'rgba(108,92,231,0.14)',
            border: '1px solid rgba(108,92,231,0.55)',
            color: '#e5e7f0',
            padding: '0.85rem 1rem',
            borderRadius: '10px',
            fontSize: '13.5px',
            boxShadow: '0 10px 30px rgba(0,0,0,0.4)',
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: '0.4rem' }}>New AE402 version available</div>
          <div style={{ color: '#b6bdd1', marginBottom: '0.75rem' }}>
            Reload to activate the update. If you're mid-transaction, finish it first.
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
            <button
              type="button"
              onClick={() => setUpdate(null)}
              style={{
                background: 'transparent',
                color: '#cbd0ff',
                border: '1px solid rgba(108,92,231,0.5)',
                padding: '0.4rem 0.75rem',
                borderRadius: '8px',
                cursor: 'pointer',
                fontSize: '12.5px',
              }}
            >
              Later
            </button>
            <button
              type="button"
              onClick={async () => {
                const activate = update.activate
                setUpdate(null)
                await activate()
              }}
              style={{
                background: '#6C5CE7',
                color: 'white',
                border: 'none',
                padding: '0.4rem 0.85rem',
                borderRadius: '8px',
                cursor: 'pointer',
                fontSize: '12.5px',
                fontWeight: 600,
              }}
            >
              Reload
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
