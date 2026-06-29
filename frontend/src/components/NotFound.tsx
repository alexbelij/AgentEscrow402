import { Link } from 'react-router-dom'
import { ArrowLeft, ShieldOff } from 'lucide-react'

export default function NotFound() {
  return (
    <section className="min-h-[80vh] flex items-center justify-center">
      <div className="text-center px-4 animate-fade-in-up">
        <ShieldOff size={56} className="text-ae-accent/50 mx-auto mb-4" />
        <h1 className="text-6xl sm:text-8xl font-extrabold ae-gradient-text mb-4">404</h1>
        <p className="text-xl text-white font-semibold mb-2">Escrow Not Found</p>
        <p className="text-ae-gray mb-8 max-w-sm mx-auto">This transaction doesn't exist in the ledger.</p>
        <Link to="/" className="ae-btn-primary"><ArrowLeft size={18} /> Back to Home</Link>
      </div>
    </section>
  )
}
