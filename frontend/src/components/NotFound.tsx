export default function NotFound() {
  return (
    <div className="min-h-screen bg-ae-bg flex items-center justify-center px-4">
      <div className="text-center max-w-md">
        <img src="/images/mascot/maskot_sad.png" alt="" className="w-40 mx-auto mb-6 animate-rocket-glow" />
        <p className="text-purple-400 text-sm font-semibold mb-2">ESCROW NOT FOUND</p>
        <h1 className="text-6xl font-extrabold text-white mb-3">404</h1>
        <p className="text-gray-500 mb-8">This transaction doesn't exist on any chain.</p>
        <a href="/" className="inline-flex items-center gap-2 px-6 py-3 bg-ae-accent text-white font-semibold rounded-xl hover:bg-ae-accent-bright transition-colors">Return Home</a>
      </div>
    </div>
  )
}
