import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

/**
 * PWA offline shell configuration.
 *
 * Strategy:
 *   - App shell (HTML, JS, CSS, fonts, static images) is precached at install
 *     time so the console loads without network on second launch.
 *   - `/backend/api/**` GET calls (contracts, escrow reads, etc.) use
 *     NetworkFirst so live data still wins when online, but the last-good
 *     payload is served when offline.
 *   - `/backend/events` SSE stream is explicitly NOT cached (NetworkOnly) —
 *     an SSE cache would break stream semantics.
 *   - Write endpoints (POST/PUT/PATCH/DELETE) are NEVER cached.
 *   - Google Fonts get a StaleWhileRevalidate cache for offline text.
 *
 * The registration is `prompt`: the app decides when to activate an update
 * so a live escrow flow does not get interrupted mid-signature.
 */
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      strategies: 'generateSW',
      registerType: 'prompt',
      injectRegister: null, // registered manually from src/lib/pwa.ts
      includeAssets: [
        'favicon.ico',
        'favicon-16x16.png',
        'favicon-32x32.png',
        'apple-touch-icon.png',
        'robots.txt',
        'sitemap.xml',
        'images/casper-logo.png',
        'images/casper-wordmark-white.png',
        'images/logo.webp',
        'images/og-ae402.png',
      ],
      manifest: {
        id: '/',
        name: 'AgentEscrow402 Console',
        short_name: 'AE402',
        description:
          'x402-compatible escrow payments for AI agents on Casper Network. Offline-capable console for escrow lifecycle, arbitration, and evidence review.',
        theme_color: '#0a0a1a',
        background_color: '#0a0a1a',
        display: 'standalone',
        orientation: 'any',
        scope: '/',
        start_url: '/console',
        lang: 'en',
        categories: ['finance', 'productivity', 'developer'],
        icons: [
          {
            src: '/apple-touch-icon.png',
            sizes: '180x180',
            type: 'image/png',
            purpose: 'any',
          },
          {
            src: '/favicon-32x32.png',
            sizes: '32x32',
            type: 'image/png',
          },
          {
            src: '/favicon-16x16.png',
            sizes: '16x16',
            type: 'image/png',
          },
          {
            src: '/images/logo.webp',
            sizes: '512x512',
            type: 'image/webp',
            purpose: 'any',
          },
          {
            src: '/images/logo.webp',
            sizes: '512x512',
            type: 'image/webp',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,ico,png,svg,webp,woff2}'],
        // Vite's chunker can produce large main bundles for a fully-featured
        // console, so raise the precache size limit to a still-sane 4 MiB per
        // file (network transfer is still gzipped).
        maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
        cleanupOutdatedCaches: true,
        // IMPORTANT: this must be the SPA app shell (`index.html`), not the
        // static `offline.html` page. `navigateFallback` is served for
        // *every* navigation that isn't an exact precache hit (i.e. every
        // client-routed URL like `/console/docs`), unconditionally — not
        // only when offline. Pointing it at `offline.html` previously broke
        // every deep-linked route (they always rendered the offline shell
        // instead of the real app, even online). `offline.html` is still
        // precached and still used for the case where fetching the app
        // shell itself truly cannot be served (see workbox `catchHandler`
        // semantics) — it must never be the primary navigation handler.
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [
          // Never fall back for API traffic or the SSE stream.
          /^\/backend\//,
          // Never intercept OAuth-style third-party redirects.
          /^\/oauth\//,
        ],
        runtimeCaching: [
          // API reads: try network, fall back to cache when offline.
          {
            urlPattern: ({ url, request }) =>
              request.method === 'GET' &&
              url.pathname.startsWith('/backend/') &&
              !url.pathname.startsWith('/backend/events'),
            handler: 'NetworkFirst',
            options: {
              cacheName: 'ae402-backend-api',
              networkTimeoutSeconds: 5,
              expiration: {
                maxEntries: 200,
                maxAgeSeconds: 60 * 60 * 24, // 24h
              },
              cacheableResponse: { statuses: [0, 200] },
              matchOptions: { ignoreVary: true },
            },
          },
          // WASM assets fetched via /backend/wasm/* are content-addressed.
          {
            urlPattern: ({ url, request }) =>
              request.method === 'GET' && url.pathname.startsWith('/backend/wasm/'),
            handler: 'CacheFirst',
            options: {
              cacheName: 'ae402-backend-wasm',
              expiration: {
                maxEntries: 30,
                maxAgeSeconds: 60 * 60 * 24 * 30, // 30d
              },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          // Google Fonts stylesheet.
          {
            urlPattern: /^https:\/\/fonts\.googleapis\.com\/.*/i,
            handler: 'StaleWhileRevalidate',
            options: {
              cacheName: 'google-fonts-css',
              expiration: { maxEntries: 20, maxAgeSeconds: 60 * 60 * 24 * 365 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          // Google Fonts static (woff2).
          {
            urlPattern: /^https:\/\/fonts\.gstatic\.com\/.*/i,
            handler: 'CacheFirst',
            options: {
              cacheName: 'google-fonts-static',
              expiration: { maxEntries: 40, maxAgeSeconds: 60 * 60 * 24 * 365 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          // Own-origin images.
          {
            urlPattern: ({ url, request, sameOrigin }) =>
              request.method === 'GET' &&
              sameOrigin &&
              /\.(png|webp|jpg|jpeg|gif|svg|ico)$/i.test(url.pathname),
            handler: 'CacheFirst',
            options: {
              cacheName: 'ae402-images',
              expiration: { maxEntries: 100, maxAgeSeconds: 60 * 60 * 24 * 30 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
      devOptions: {
        // Do not activate the service worker under `vite dev` — noisy and
        // makes hot-reload flaky.
        enabled: false,
        type: 'module',
      },
    }),
  ],
  build: { outDir: 'dist', sourcemap: false },
  server: { port: 3000 },
})
