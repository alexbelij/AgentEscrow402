export default function Problem() {
  return (
    <section className="py-16 sm:py-24">
      <div className="ae-section">
        <h2 className="text-2xl sm:text-3xl font-bold text-center mb-4">
          The Agent Economy Has <span className="ae-gradient-text">No Payment Layer</span>
        </h2>
        <p className="text-ae-gray text-center max-w-lg mx-auto mb-10">
          AI agents process millions of tasks daily. Without payment escrow, every transaction is a leap of faith.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 max-w-3xl mx-auto">
          {[
            { stat: '$0', text: 'recovered when an AI agent defaults on a task' },
            { stat: '0%', text: 'of agent frameworks include payment guarantees' },
            { stat: 'No', text: 'trust = no autonomous commerce' },
          ].map(c => (
            <div key={c.stat} className="ae-card text-center">
              <div className="text-4xl sm:text-5xl font-extrabold ae-gradient-text mb-2">{c.stat}</div>
              <p className="text-sm text-ae-gray leading-relaxed">{c.text}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
