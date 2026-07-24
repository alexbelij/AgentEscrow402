# PWA Offline Shell

*Status: shipped in `feat/ae402-pwa-offline-shell`. Serves the AE402 console
as an installable Progressive Web App with an offline-capable shell.*

## What ships

The `frontend/` bundle (Vite + React + TS) now emits three PWA artifacts on
`npm run build`:

- `dist/manifest.webmanifest` — installability metadata (name, icons,
  `start_url: /console`, `display: standalone`).
- `dist/sw.js` — Workbox service worker (precache + runtime rules).
- `dist/offline.html` — plain-HTML fallback used when a navigation request
  cannot be served from network or cache.

The `<link rel="manifest">` tag is injected into `index.html` automatically
by `vite-plugin-pwa`.

## Threat model / boundaries

We ship an *additive* offline shell. It never mutates existing runtime
behavior when the network is healthy.

- **Reads (`GET /backend/**`)** — served `NetworkFirst` (5s timeout). Live
  data always wins when online. Cache is a soft fallback, capped at 200
  entries / 24h.
- **Writes (`POST/PUT/PATCH/DELETE`)** — never intercepted, never cached.
  Signed deploys always go to Render.
- **SSE (`/backend/events`)** — explicitly excluded from any cache
  (`NetworkOnly`). Stream semantics stay intact; the existing exponential
  backoff in `useEscrowEvents.ts` still governs reconnects.
- **WASM (`/backend/wasm/*`)** — `CacheFirst`. Content-addressed; safe to
  cache aggressively (30 entries / 30d).
- **Third-party fonts** — Google Fonts cached (`SWR` for CSS, `CacheFirst`
  for `woff2`) so console text renders offline.

`navigateFallbackDenylist` prevents the SW from ever intercepting API or
OAuth callbacks with the offline HTML page.

## Update policy

`registerType: 'prompt'` — a new SW *does not* auto-activate. Instead:

1. `src/lib/pwa.ts` calls Workbox's `registerSW` with `onNeedRefresh` +
   `onOfflineReady` callbacks that dispatch `window` events.
2. `PWAUpdatePrompt.tsx` listens for those events and renders a
   self-contained toast (a) "New AE402 version available — Reload / Later"
   (b) "Offline-ready ✅".
3. Only when the user clicks *Reload* do we call `updateSW(true)`, which
   posts `SKIP_WAITING` to the waiting SW and reloads the page.

This keeps a mid-flight escrow signature from being interrupted by an
unexpected page swap.

## Cache buckets

| Cache | Strategy | Scope | Cap |
| --- | --- | --- | --- |
| `ae402-precache` | Precache | HTML/JS/CSS/PNG/WEBP/WOFF2 in `dist/**` | ~40 files, gate is `<= 4 MiB / file` |
| `ae402-backend-api` | NetworkFirst 5s | `GET /backend/**` (except `/events`) | 200 entries, 24h |
| `ae402-backend-wasm` | CacheFirst | `GET /backend/wasm/**` | 30 entries, 30d |
| `google-fonts-css` | StaleWhileRevalidate | `fonts.googleapis.com` | 20, 1y |
| `google-fonts-static` | CacheFirst | `fonts.gstatic.com` | 40, 1y |
| `ae402-images` | CacheFirst | Same-origin images | 100, 30d |

`cleanupOutdatedCaches: true` — Workbox removes previous precache
generations on activation.

## Files

- `frontend/vite.config.ts` — full PWA config.
- `frontend/src/lib/pwa.ts` — SW registration + last-path tracker.
- `frontend/src/components/PWAUpdatePrompt.tsx` — toast surface for
  "update available" / "offline ready".
- `frontend/src/main.tsx` — calls `registerPWA()` + `trackLastPathForOfflineFallback()`.
- `frontend/src/App.tsx` — mounts `<PWAUpdatePrompt />` once at root.
- `frontend/src/vite-env.d.ts` — adds `vite-plugin-pwa/client` reference so
  `virtual:pwa-register` types resolve.
- `frontend/public/offline.html` — offline fallback page (self-contained,
  no bundle deps).
- `frontend/vercel.json` — cache headers so `sw.js`, `workbox-*.js`,
  `manifest.webmanifest`, `offline.html` are always revalidated.

## Verification

```bash
cd frontend
npm run build
# → produces dist/sw.js, dist/workbox-*.js, dist/manifest.webmanifest, dist/offline.html
```

The plugin also prints a summary:

```
PWA v1.3.0
mode      generateSW
precache  40 entries (~7.9 MiB)
files generated
  dist/sw.js
  dist/workbox-<hash>.js
```

**Local smoke test** (production build):

```bash
cd frontend
npm run build
npx serve dist -l 3000
```

Then in Chrome DevTools → Application → Service Workers: SW should show
`activated`. Toggle DevTools → Network → *Offline*, refresh `/console/overview` —
the shell loads and API errors trigger the last-good-cache fallback where
present.

## Production deploy

Vercel deploys `frontend/` on push to `main`. `vercel.json` adds a
`Service-Worker-Allowed: /` header so the SW can control the whole origin,
and forces the SW / manifest / offline page to always revalidate (no CDN
staleness).

Rollout is otherwise transparent: on the first visit after deploy, the SW
installs and precaches; subsequent visits load offline-capable.

## Non-goals

- **Background sync** — the console still requires the user to be online
  to broadcast on-chain deploys. Casper transactions are not queued for
  later.
- **Push notifications** — Telegram bridge already covers server-push
  paths (see `docs/TELEGRAM_BRIDGE.md`). Web push is out of scope.
- **Dev-mode SW** — deliberately disabled (`devOptions.enabled: false`) to
  keep HMR fast and prevent stale caches from previous production builds
  from hijacking `vite dev`.

## Related

- `docs/TELEGRAM_BRIDGE.md` — companion push channel.
- `docs/VC_RECEIPTS.md` — offline-verifiable escrow receipts.
- `frontend/README.md` — Vite dev workflow.
