import { useState } from 'react'

export default function SuggestionChips({ suggestions, onSend }) {
  const [hoveredIdx, setHoveredIdx] = useState(null)

  if (!suggestions || suggestions.length === 0) return null

  return (
    <div
      style={{
        padding: '10px 16px 8px',
        display: 'flex',
        flexWrap: 'wrap',
        gap: 7,
        borderTop: '1px solid var(--border)',
        background: 'var(--surface)',
      }}
    >
      <span
        style={{
          width: '100%',
          fontFamily: 'var(--font-mono)',
          fontSize: 9.5,
          color: 'var(--text-dim)',
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          marginBottom: 2,
        }}
        aria-hidden="true"
      >
        Ask next
      </span>
      {suggestions.map((s, i) => (
        <button
          key={i}
          onClick={() => onSend(s)}
          onMouseEnter={() => setHoveredIdx(i)}
          onMouseLeave={() => setHoveredIdx(null)}
          onKeyDown={(e) => e.key === 'Enter' && onSend(s)}
          aria-label={`Ask: ${s}`}
          style={{
            background: 'var(--surface2)',
            border: `1px solid ${hoveredIdx === i ? 'var(--accent-border)' : 'var(--border-bright)'}`,
            borderRadius: 20,
            color: hoveredIdx === i ? 'var(--accent)' : 'var(--text-muted)',
            fontSize: 12,
            fontFamily: 'var(--font-sans)',
            padding: '5px 12px 5px 10px',
            cursor: 'pointer',
            transition: 'border-color 0.15s, color 0.15s, box-shadow 0.15s',
            boxShadow: hoveredIdx === i ? '0 0 8px var(--accent-glow)' : 'none',
            maxWidth: 320,
            display: 'flex',
            alignItems: 'center',
            gap: 5,
            textOverflow: 'ellipsis',
            overflow: 'hidden',
            whiteSpace: 'nowrap',
            animation: `slide-up 0.25s ease ${i * 0.08}s both`,
          }}
        >
          <span
            aria-hidden="true"
            style={{
              color: 'var(--accent)',
              fontSize: 11,
              fontFamily: 'var(--font-mono)',
              flexShrink: 0,
              opacity: hoveredIdx === i ? 1 : 0.5,
              transition: 'opacity 0.15s',
            }}
          >
            →
          </span>
          <span
            style={{
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {s}
          </span>
        </button>
      ))}
    </div>
  )
}
