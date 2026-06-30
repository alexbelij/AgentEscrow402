import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <section className="min-h-screen flex items-center justify-center relative">
      <div className="absolute inset-0 bg-gradient-to-b from-ae-bg via-[#0e0e28] to-ae-bg" />
      <div className="relative z-10 text-center px-6">
        <img src="/images/mascot/maskot_sad.png" alt="" className="w-32 mx-auto mb-6 drop-shadow-[0_0_20px_rgba(108,92,231,0.3)]" />
        <h1 className="text-6xl font-extrabold bg-gradient-to-r from-ae-accent to-cyan-400 bg-clip-text text-transparent mb-4">402</h1>
        <p className="text-xl text-gray-400 mb-2">Payment Required... or maybe wrong page?</p>
        <p className="text-sm text-gray-500 mb-8">This page doesn't exist. The escrow was never created.</p>
        <Link to="/" className="inline-flex items-center gap-2 px-6 py-3 rounded-lg bg-ae-accent text-white font-semibold hover:scale-[1.02] transition-transform">
          Back to Home
        </Link>
      </div>
    </section>
  )
}
