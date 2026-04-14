import { useState, useEffect } from 'react'

const ARTIFACT_LABELS = {
  duty_cycle_calculator: 'Duty Cycle Calculator',
  polarity_diagram: 'Polarity Diagram',
  troubleshooting_flowchart: 'Troubleshooting Guide',
  settings_configurator: 'Settings Configurator',
  wiring_diagram: 'Wiring Diagram',
}

function LoadingSkeleton() {
  return (
    <div
      role="status"
      aria-label="Loading interactive content"
      style={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 20,
        padding: 40,
      }}
    >
      {/* Pulsing glow orb */}
      <div
        aria-hidden="true"
        style={{
          width: 56,
          height: 56,
          borderRadius: '50%',
          background: 'var(--accent-dim)',
          border: '2px solid var(--accent-border)',
          animation: 'weld-glow 1.6s ease-in-out infinite',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <div
          style={{
            width: 12,
            height: 12,
            borderRadius: '50%',
            background: 'var(--accent)',
            animation: 'pulse-dot 1.6s ease-in-out infinite',
          }}
        />
      </div>

      {/* Shimmer bars */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, width: '100%', maxWidth: 260 }}>
        {[80, 60, 72, 50].map((w, i) => (
          <div
            key={i}
            aria-hidden="true"
            style={{
              height: 10,
              borderRadius: 5,
              width: `${w}%`,
              background: 'linear-gradient(90deg, var(--surface2) 25%, var(--surface3) 50%, var(--surface2) 75%)',
              backgroundSize: '200% 100%',
              animation: `shimmer 1.8s ease-in-out ${i * 0.1}s infinite`,
            }}
          />
        ))}
      </div>

      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--text-muted)',
          letterSpacing: '0.04em',
        }}
      >
        Generating interactive content\u2026
      </span>
    </div>
  )
}

function EmptyPanelState() {
  const processes = [
    { label: 'MIG', desc: 'Settings configurator' },
    { label: 'TIG', desc: 'Polarity diagram' },
    { label: 'FCAW', desc: 'Troubleshooting guide' },
    { label: 'STICK', desc: 'Duty cycle calculator' },
  ]

  return (
    <div
      style={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 24,
        padding: 32,
        color: 'var(--text-muted)',
        textAlign: 'center',
      }}
    >
      {/* Grid icon */}
      <div aria-hidden="true" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
        {processes.map((p) => (
          <div
            key={p.label}
            style={{
              background: 'var(--surface2)',
              border: '1px solid var(--border)',
              borderRadius: 8,
              padding: '10px 14px',
              textAlign: 'left',
            }}
          >
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                fontWeight: 700,
                color: 'var(--accent)',
                marginBottom: 3,
              }}
            >
              {p.label}
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-dim)' }}>{p.desc}</div>
          </div>
        ))}
      </div>

      <div>
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 13,
            fontWeight: 600,
            color: 'var(--text-muted)',
            marginBottom: 6,
          }}
        >
          Interactive Panel
        </div>
        <div style={{ fontSize: 12, lineHeight: 1.5 }}>
          Ask about duty cycles, polarity setup,
          <br />
          or troubleshooting to activate
        </div>
      </div>
    </div>
  )
}

export default function ArtifactPanel({ artifact, agentPhase, isPinned, onPin, onUnpin }) {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (artifact) {
      setVisible(false)
      const t = setTimeout(() => setVisible(true), 50)
      return () => clearTimeout(t)
    }
  }, [artifact])

  const panelTitle = artifact
    ? (ARTIFACT_LABELS[artifact.type] ?? artifact.type.replace(/_/g, ' '))
    : 'Interactive Panel'

  const isThinking = agentPhase === 'thinking' || agentPhase === 'streaming'

  return (
    <div
      style={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--surface)',
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '12px 20px',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexShrink: 0,
          gap: 8,
        }}
      >
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontWeight: artifact ? 600 : 400,
            fontSize: 11,
            color: artifact ? 'var(--accent)' : 'var(--text-muted)',
            letterSpacing: '0.06em',
            textTransform: 'uppercase',
            transition: 'color 0.3s',
            flex: 1,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {isPinned && <span aria-hidden="true" style={{ marginRight: 5 }}>📌</span>}
          {panelTitle}
        </span>

        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          {/* Pin / Unpin button */}
          {artifact && (
            <button
              onClick={isPinned ? onUnpin : onPin}
              title={isPinned ? 'Unpin — new responses will replace this' : 'Pin — keep this artifact while you keep chatting'}
              aria-label={isPinned ? 'Unpin artifact' : 'Pin artifact'}
              style={{
                background: isPinned ? 'var(--accent-dim)' : 'none',
                border: `1px solid ${isPinned ? 'var(--accent-border)' : 'var(--border-bright)'}`,
                borderRadius: 4,
                padding: '2px 8px',
                color: isPinned ? 'var(--accent)' : 'var(--text-muted)',
                fontFamily: 'var(--font-mono)',
                fontSize: 9,
                fontWeight: 600,
                letterSpacing: '0.06em',
                textTransform: 'uppercase',
                cursor: 'pointer',
                transition: 'background 0.15s, color 0.15s, border-color 0.15s',
                display: 'flex',
                alignItems: 'center',
                gap: 4,
              }}
            >
              <span aria-hidden="true">{isPinned ? '📌' : '📍'}</span>
              {isPinned ? 'Pinned' : 'Pin'}
            </button>
          )}

          {/* Live / Pinned status badge */}
          {artifact && (
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 9,
                color: isPinned ? 'var(--text-muted)' : 'var(--success)',
                letterSpacing: '0.06em',
                textTransform: 'uppercase',
                border: `1px solid ${isPinned ? 'var(--border)' : 'var(--success)'}`,
                borderRadius: 4,
                padding: '1px 6px',
                opacity: 0.8,
              }}
            >
              {isPinned ? 'Pinned' : 'Live'}
            </span>
          )}
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflow: 'hidden', position: 'relative' }}>
        {artifact ? (
          <div
            style={{
              opacity: visible ? 1 : 0,
              transition: 'opacity 0.35s ease',
              height: '100%',
            }}
          >
            <iframe
              srcDoc={artifact.html}
              sandbox="allow-scripts"
              title={panelTitle}
              style={{
                width: '100%',
                height: '100%',
                border: 'none',
                display: 'block',
              }}
            />
          </div>
        ) : isThinking ? (
          <LoadingSkeleton />
        ) : (
          <EmptyPanelState />
        )}
      </div>
    </div>
  )
}
