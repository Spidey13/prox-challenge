import { useEffect, useRef } from 'react'
import HighlightOverlay from './HighlightOverlay'

export default function ImageModal({ image, onClose }) {
  const closeRef = useRef(null)

  useEffect(() => {
    closeRef.current?.focus()

    const handleKey = (e) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [onClose])

  const docLabel = image.doc_slug?.replace(/-/g, ' ') ?? 'manual'

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Page ${image.page_number} of ${docLabel}`}
      onClick={onClose}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') onClose() }}
      tabIndex={-1}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        background: 'rgba(0,0,0,0.85)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
        animation: 'fade-in 0.15s ease',
        overscrollBehavior: 'contain',
      }}
    >
      <div
        role="document"
        onClick={e => e.stopPropagation()}
        onKeyDown={e => e.stopPropagation()}
        style={{
          position: 'relative',
          background: 'var(--surface)',
          border: '1px solid var(--border-bright)',
          borderRadius: 12,
          overflow: 'hidden',
          maxWidth: '90vw',
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 24px 64px rgba(0,0,0,0.6)',
          animation: 'slide-up 0.2s ease',
        }}
      >
        {/* Modal header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '10px 16px',
            borderBottom: '1px solid var(--border)',
            gap: 16,
          }}
        >
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--text-muted)',
              letterSpacing: '0.04em',
              textTransform: 'uppercase',
            }}
          >
            Page {image.page_number + 1}
            {image.doc_slug ? ` \u2014 ${docLabel}` : ''}
          </span>
          <button
            ref={closeRef}
            onClick={onClose}
            aria-label="Close image viewer"
            style={{
              background: 'none',
              border: '1px solid var(--border)',
              borderRadius: 6,
              color: 'var(--text-muted)',
              cursor: 'pointer',
              padding: '3px 10px',
              fontSize: 12,
              fontFamily: 'var(--font-mono)',
              transition: 'border-color 0.15s, color 0.15s',
            }}
            onMouseEnter={e => {
              e.currentTarget.style.borderColor = 'var(--accent)'
              e.currentTarget.style.color = 'var(--accent)'
            }}
            onMouseLeave={e => {
              e.currentTarget.style.borderColor = 'var(--border)'
              e.currentTarget.style.color = 'var(--text-muted)'
            }}
          >
            ESC
          </button>
        </div>

        {/* Image with highlight */}
        <div
          style={{
            position: 'relative',
            overflow: 'auto',
            maxHeight: 'calc(90vh - 56px)',
          }}
        >
          <div style={{ position: 'relative', display: 'inline-block', minWidth: '100%' }}>
            <img
              src={image.url}
              alt={`Manual page ${image.page_number + 1}`}
              width={800}
              height={1035}
              style={{
                display: 'block',
                maxWidth: '80vw',
                height: 'auto',
              }}
            />
            {image.highlight && <HighlightOverlay highlight={image.highlight} />}
          </div>
        </div>
      </div>
    </div>
  )
}
