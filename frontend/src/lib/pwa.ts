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
            // `updateSW(true)` (vite-plugin-pwa's registerSW, `prompt` mode)
            // only posts SKIP_WAITING to the waiting worker; it resolves as
            // soon as the message is sent, well before the new worker has
            // actually activated and taken control of this page. A previous
            // version force-reloaded in a `finally` block right after that
            // await, which fired the reload *before* the new SW controlled
            // the page: the browser re-requested the app shell, which was
            // still served by the OLD (about-to-be-replaced) worker/cache,
            // referencing that old build's hashed JS filenames. Those files
            // no longer exist on the latest Vercel deployment, so the
            // request 404s, falls through to the SPA catch-all rewrite, and
            // comes back as `index.html` (text/html) where a JS module was
            // expected -> "Failed to load module script" -> black screen
            // that only cleared on a *second*, manual reload (by which time
            // the new SW really was in control).
            //
            // registerSW's own internal `controlling` listener (registered
            // when the "update available" prompt was first shown) already
            // calls `window.location.reload()` for us, but only once the
            // browser actually reports the new worker as in control -- so
            // we let that fire instead of racing it. We still guard with a
            // one-shot fallback timer in case `controllerchange` never
            // fires (seen in some multi-tab setups), but give it enough
            // headroom to not repeat the same race.
            let reloaded = false
            const reloadOnce = () => {
              if (reloaded) return
              reloaded = true
              window.location.reload()
            }
            if ('serviceWorker' in navigator) {
              navigator.serviceWorker.addEventListener('controllerchange', reloadOnce, { once: true })
            }
            await updateSW(true)
            // Fallback only — gives the browser time to actually hand
            // control to the new worker before we force it ourselves.
            setTimeout(reloadOnce, 5000)
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
