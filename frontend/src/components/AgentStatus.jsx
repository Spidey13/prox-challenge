import { useState, useEffect } from 'react'

const PHASES = [
  { maxMs: 2000, label: 'Searching manual\u2026' },
  { maxMs: 5000, label: 'Analyzing content\u2026' },
  { maxMs: 10000, label: 'Generating response\u2026' },
  { maxMs: Infinity, label: 'Working on a detailed answer\u2026' },
]

function getPhaseLabel(elapsedMs) {
  for (const phase of PHASES) {
    if (elapsedMs < phase.maxMs) return phase.label
  }
  return PHASES[PHASES.length - 1].label
}

export default function AgentStatus({ agentPhase, thinkingStart }) {
  const [label, setLabel] = useState(PHASES[0].label)

  useEffect(() => {
    if (agentPhase !== 'thinking' || !thinkingStart) return

    const update = () => {
      const elapsed = Date.now() - thinkingStart
      setLabel(getPhaseLabel(elapsed))
    }

    update()
    const interval = setInterval(update, 500)
    return () => clearInterval(interval)
  }, [agentPhase, thinkingStart])

  if (agentPhase !== 'thinking') return null

  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={label}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '8px 0',
        animation: 'fade-in 0.2s ease',
      }}
    >
      {/* Pulsing dot trio */}
      <div
        style={{ display: 'flex', gap: 4, alignItems: 'center', flexShrink: 0 }}
        aria-hidden="true"
      >
        {[0, 1, 2].map(i => (
          <div
            key={i}
            style={{
              width: 5,
              height: 5,
              borderRadius: '50%',
              background: 'var(--accent)',
              animation: `pulse-dot 1.2s ease-in-out ${i * 0.18}s infinite`,
            }}
          />
        ))}
      </div>

      {/* Phase label */}
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11.5,
          color: 'var(--text-muted)',
          letterSpacing: '0.02em',
          transition: 'opacity 0.3s',
        }}
      >
        {label}
      </span>
    </div>
  )
}
