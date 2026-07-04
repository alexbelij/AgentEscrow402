import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { ClickProvider } from './lib/click'
import { SignerProvider } from './lib/signer'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ClickProvider>
      <SignerProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </SignerProvider>
    </ClickProvider>
  </StrictMode>
)
