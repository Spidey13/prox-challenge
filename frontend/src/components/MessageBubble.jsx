import { useMemo } from 'react'
import { marked } from 'marked'
import ImageCitation from './ImageCitation'

// Configure marked once
marked.setOptions({ breaks: true, gfm: true })

export default function MessageBubble({ message, onViewArtifact }) {
  const isUser = message.role === 'user'

  const htmlContent = useMemo(() => {
    if (isUser || !message.content) return null
    return marked.parse(message.content)
  }, [isUser, message.content])

  const images = message.images ?? []
  const hasArtifact = !isUser && !!message.artifact && message.done

  const ARTIFACT_LABELS = {
    duty_cycle_calculator: 'Duty Cycle Calculator',
    polarity_diagram: 'Polarity Diagram',
    troubleshooting_flowchart: 'Troubleshooting Guide',
    settings_configurator: 'Settings Configurator',
    wiring_diagram: 'Wiring Diagram',
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: isUser ? 'flex-end' : 'flex-start',
        gap: 8,
        animation: 'fade-in 0.2s ease',
      }}
    >
      {/* User image attachment — shown above the text bubble */}
      {isUser && message.imagePreviewUrl && (
        <div
          style={{
            maxWidth: '78%',
            borderRadius: '14px 14px 4px 14px',
            overflow: 'hidden',
            border: '1px solid var(--user-bubble-border)',
          }}
        >
          <img
            src={message.imagePreviewUrl}
            alt="Attached image"
            style={{
              display: 'block',
              maxWidth: '100%',
              maxHeight: 240,
              objectFit: 'contain',
              background: 'var(--surface2)',
            }}
          />
        </div>
      )}

      {/* Message bubble */}
      <div
        style={{
          maxWidth: isUser ? '78%' : '100%',
          width: isUser ? undefined : '100%',
          background: isUser ? 'var(--user-bubble)' : 'transparent',
          border: isUser ? '1px solid var(--user-bubble-border)' : 'none',
          borderRadius: isUser
            ? '14px 14px 4px 14px'
            : 0,
          padding: isUser ? '9px 14px' : '2px 0',
          fontSize: 14,
          color: 'var(--text)',
        }}
      >
        {isUser ? (
          <span style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
            {message.content}
          </span>
        ) : (
          <div
            className="markdown-body"
            dangerouslySetInnerHTML={{ __html: htmlContent ?? '' }}
          />
        )}
      </div>

      {/* Image citation row — only for assistant messages */}
      {!isUser && images.length > 0 && (
        <div
          role="list"
          aria-label="Referenced manual pages"
          style={{
            display: 'flex',
            flexDirection: 'row',
            flexWrap: 'wrap',
            gap: 8,
            paddingTop: 4,
          }}
        >
          {images.map((img, i) => (
            <div key={i} role="listitem">
              <ImageCitation image={img} />
            </div>
          ))}
        </div>
      )}

      {/* Inline "View artifact" button — appears after message is done */}
      {hasArtifact && onViewArtifact && (
        <button
          onClick={() => onViewArtifact(message.artifact)}
          title="Load this interactive tool into the right panel"
          style={{
            background: 'var(--accent-dim)',
            border: '1px solid var(--accent-border)',
            borderRadius: 6,
            padding: '4px 10px',
            color: 'var(--accent)',
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            fontWeight: 600,
            letterSpacing: '0.06em',
            textTransform: 'uppercase',
            cursor: 'pointer',
            transition: 'background 0.15s, box-shadow 0.15s',
            display: 'flex',
            alignItems: 'center',
            gap: 5,
          }}
          onMouseEnter={e => {
            e.currentTarget.style.background = 'var(--accent-glow)'
            e.currentTarget.style.boxShadow = '0 0 8px var(--accent-glow)'
          }}
          onMouseLeave={e => {
            e.currentTarget.style.background = 'var(--accent-dim)'
            e.currentTarget.style.boxShadow = 'none'
          }}
          aria-label={`View ${ARTIFACT_LABELS[message.artifact?.type] ?? 'artifact'}`}
        >
          <span aria-hidden="true">⚡</span>
          {ARTIFACT_LABELS[message.artifact?.type] ?? message.artifact?.type?.replace(/_/g, ' ') ?? 'Artifact'}
        </button>
      )}
    </div>
  )
}
