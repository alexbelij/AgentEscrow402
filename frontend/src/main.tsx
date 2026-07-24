import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { ClickProvider } from './lib/click'
import { SignerProvider } from './lib/signer'
import { ToastProvider } from './lib/toast'
import { registerPWA, trackLastPathForOfflineFallback } from './lib/pwa'
import './index.css'

// Fire-and-forget: register the service worker (no-op in dev / when SW is
// unavailable). Captures registration failures on its own.
void registerPWA()

// Remember the current path so /offline.html's Retry button can restore it.
trackLastPathForOfflineFallback()
if (typeof window !== 'undefined') {
  window.addEventListener('popstate', trackLastPathForOfflineFallback)
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ToastProvider>
      <ClickProvider>
        <SignerProvider>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </SignerProvider>
      </ClickProvider>
    </ToastProvider>
  </StrictMode>
)
