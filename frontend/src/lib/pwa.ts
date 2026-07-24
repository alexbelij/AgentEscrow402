/**
 * Progressive-Web-App runtime hooks.
 *
 * Two responsibilities:
 *  1. Register the Workbox-generated service worker (only in production).
 *  2. Publish a lightweight event API the React tree can subscribe to for the
 *     "update available" and "offline ready" toasts without adding another
 *     global state dependency.
 *
 * Contract:
 *   - `window` event `ae402:pwa:need-refresh` fires when a new SW is waiting.
 *     Payload: `{ activate: () => Promise<void> }`.
 *   - `window` event `ae402:pwa:offline-ready` fires once the SW is installed
 *     for the first time and the app is now usable offline.
 *   - The Workbox `registerSW` module is dynamically imported so the code
 *     path is dead-stripped in dev builds (where the plugin is disabled).
 *
 * Manual registration (via `injectRegister: null` in vite.config.ts) lets us
 * gate registration on production, and control update timing so a live
 * escrow signature isn't interrupted mid-flow.
 */

export interface PWAEvents {
  'ae402:pwa:need-refresh': CustomEvent<{ activate: () => Promise<void> }>
  'ae402:pwa:offline-ready': CustomEvent<void>
}

function dispatch<K extends keyof PWAEvents>(name: K, detail?: PWAEvents[K]['detail']) {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent(name, { detail } as CustomEventInit))
}

/**
 * Register the service worker. Safe to call multiple times — the underlying
 * `registerSW` is idempotent per document.
 */
export async function registerPWA(): Promise<void> {
  if (typeof window === 'undefined') return
  if (!('serviceWorker' in navigator)) return
  // Only register in production. In dev the plugin is disabled and any
  // stale SW from a previous production build would intercept module HMR.
  if (!import.meta.env.PROD) return

  try {
    const mod = await import('virtual:pwa-register')
    const updateSW = mod.registerSW({
      immediate: false,
      onNeedRefresh() {
        // Do NOT auto-reload — let the UI ask the user, so a mid-flight
        // signature/broadcast isn't destroyed by a page swap.
        dispatch('ae402:pwa:need-refresh', {
          activate: async () => {
            // `updateSW(true)` only posts SKIP_WAITING and *relies* on the
            // browser firing a `controlling` change event to reload — that
            // event can be missed/delayed (multiple tabs, timing quirks),
            // which made the button look like it did nothing. Force the
            // reload ourselves unconditionally so the click always has a
            // visible effect.
            try {
              await updateSW(true)
            } finally {
              window.location.reload()
            }
          },
        })
      },
      onOfflineReady() {
        dispatch('ae402:pwa:offline-ready')
      },
      onRegisterError(err) {
        // Non-fatal: the console still works, just without offline support.
        console.warn('[ae402:pwa] SW registration failed', err)
      },
    })
  } catch (err) {
    // Dynamic-import failure (dev builds where the virtual module doesn't
    // exist). Treat as a no-op.
    console.debug('[ae402:pwa] registerSW skipped:', err)
  }
}

/** Remember the last visited path so /offline.html's Retry button can return there. */
export function trackLastPathForOfflineFallback(): void {
  if (typeof window === 'undefined') return
  try {
    sessionStorage.setItem('ae402:last-path', window.location.pathname + window.location.search)
  } catch {
    // sessionStorage can throw in private mode — non-fatal.
  }
}
