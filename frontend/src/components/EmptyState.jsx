import { useState } from 'react'

const SCENARIOS = [
  {
    icon: '📦',
    title: 'First-time setup',
    description: 'Walk me through the initial setup from unboxing',
    question: 'I just unboxed my Vulcan OmniPro 220. Walk me through the initial setup step by step.',
  },
  {
    icon: '🔌',
    title: 'MIG with flux-core',
    description: 'Polarity, wire tension, and cable routing',
    question: 'How do I set up for flux-cored welding? What polarity and wire tension do I need?',
  },
  {
    icon: '⚡',
    title: 'Duty cycle limits',
    description: 'How long can I weld before I need to stop?',
    question: 'What is the duty cycle for MIG welding at 200A on 240V?',
  },
  {
    icon: '🔍',
    title: 'Weld quality issues',
    description: 'Porosity, spatter, or poor penetration fixes',
    question: 'I\'m getting porosity in my flux-cored welds. What should I check?',
  },
  {
    icon: '🔄',
    title: 'Switching to TIG',
    description: 'Settings, cables, and polarity for TIG welding',
    question: 'How do I switch from MIG to TIG? What settings and cables do I need?',
  },
  {
    icon: '🔧',
    title: 'Wire birdnesting',
    description: 'Wire tangling at drive rolls or gun liner',
    question: 'My wire keeps birdnesting at the drive rolls. What should I check?',
  },
]

export default function EmptyState({ onSend }) {
  const [hoveredIdx, setHoveredIdx] = useState(null)

  return (
    <div
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '32px 24px',
        gap: 28,
        animation: 'fade-in 0.4s ease',
      }}
    >
      {/* Header */}
      <div style={{ textAlign: 'center' }}>
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 22,
            fontWeight: 700,
            color: '#e8eaf0',
            letterSpacing: '-0.03em',
            marginBottom: 6,
          }}
        >
          What do you need help with?
        </div>
        <div
          style={{
            color: 'var(--text-muted)',
            fontSize: 13,
          }}
        >
          Select a situation below or type your own question
        </div>
      </div>

      {/* Scenario cards grid */}
      <div
        role="list"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(2, 1fr)',
          gap: 10,
          width: '100%',
          maxWidth: 560,
        }}
      >
        {SCENARIOS.map((s, i) => (
          <button
            key={i}
            role="listitem"
            onClick={() => onSend(s.question)}
            onMouseEnter={() => setHoveredIdx(i)}
            onMouseLeave={() => setHoveredIdx(null)}
            aria-label={`${s.title}: ${s.description}`}
            style={{
              background: hoveredIdx === i ? 'var(--surface2)' : 'var(--surface)',
              border: `1px solid ${hoveredIdx === i ? 'var(--accent-border)' : 'var(--border)'}`,
              borderRadius: 10,
              padding: '14px 16px',
              textAlign: 'left',
              cursor: 'pointer',
              transition: 'border-color 0.15s, background 0.15s, box-shadow 0.15s',
              boxShadow: hoveredIdx === i ? `0 0 12px var(--accent-glow)` : 'none',
              animation: `slide-up 0.3s ease ${i * 0.05}s both`,
              display: 'flex',
              flexDirection: 'column',
              gap: 6,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span
                aria-hidden="true"
                style={{ fontSize: 18, lineHeight: 1, flexShrink: 0 }}
              >
                {s.icon}
              </span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontWeight: 600,
                  fontSize: 12,
                  color: hoveredIdx === i ? '#e8eaf0' : 'var(--text)',
                  letterSpacing: '-0.01em',
                  transition: 'color 0.15s',
                }}
              >
                {s.title}
              </span>
            </div>
            <p
              style={{
                color: 'var(--text-muted)',
                fontSize: 11.5,
                lineHeight: 1.4,
                margin: 0,
              }}
            >
              {s.description}
            </p>
          </button>
        ))}
      </div>
    </div>
  )
}
