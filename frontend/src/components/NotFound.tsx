export default function NotFound() {
  return (
    <div className="min-h-screen bg-ae-bg flex items-center justify-center">
      <div className="text-center">
        <img src="/images/mascot/maskot_sad.png" alt="404" className="w-40 mx-auto mb-6 animate-float opacity-80" />
        <div className="text-6xl font-black text-ae-accent mb-3 font-mono">404</div>
        <p className="text-gray-500 mb-6">This page doesn't exist</p>
        <a href="/" className="px-6 py-2 rounded-lg bg-ae-accent text-white text-sm font-semibold hover:bg-ae-accent-bright transition-colors">
          Back to Home
        </a>
      </div>
    </div>
  )
}
