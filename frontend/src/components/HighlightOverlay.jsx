import { useState } from 'react'

export default function HighlightOverlay({ highlight, compact = false }) {
  const [dismissed, setDismissed] = useState(false)

  if (!highlight || dismissed) return null

  return (
    <div
      onClick={compact ? undefined : () => setDismissed(true)}
      title={compact ? undefined : 'Click to dismiss'}
      aria-hidden="true"
      style={{
        position: 'absolute',
        left: `${highlight.x * 100}%`,
        top: `${highlight.y * 100}%`,
        width: `${highlight.w * 100}%`,
        height: `${highlight.h * 100}%`,
        border: '2px solid var(--accent)',
        backgroundColor: 'var(--accent-dim)',
        borderRadius: 2,
        cursor: compact ? 'default' : 'pointer',
        zIndex: 10,
        pointerEvents: compact ? 'none' : 'auto',
      }}
    >
      {!compact && highlight.label && (
        <span
          style={{
            position: 'absolute',
            top: -22,
            left: 0,
            background: 'var(--accent)',
            color: '#000',
            fontSize: 10,
            fontWeight: 700,
            fontFamily: 'var(--font-mono)',
            padding: '2px 6px',
            borderRadius: '3px 3px 3px 0',
            whiteSpace: 'nowrap',
            maxWidth: 200,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {highlight.label}
        </span>
      )}
    </div>
  )
}
