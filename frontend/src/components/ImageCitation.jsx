import { useState } from 'react'
import HighlightOverlay from './HighlightOverlay'
import ImageModal from './ImageModal'

export default function ImageCitation({ image }) {
  const [hovered, setHovered] = useState(false)
  const [modalOpen, setModalOpen] = useState(false)

  const docLabel = image.doc_slug?.replace(/-/g, ' ') ?? 'manual'
  const pageLabel = `p.${image.page_number + 1} \u2014 ${docLabel}`

  return (
    <>
      <button
        onClick={() => setModalOpen(true)}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        aria-label={`View ${pageLabel} from manual`}
        style={{
          background: 'none',
          border: `1px solid ${hovered ? 'var(--accent-border)' : 'var(--border)'}`,
          borderRadius: 8,
          padding: 0,
          cursor: 'pointer',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          transition: 'border-color 0.15s, box-shadow 0.15s',
          boxShadow: hovered ? '0 0 10px var(--accent-glow)' : 'none',
          flexShrink: 0,
          width: 110,
        }}
      >
        {/* Thumbnail */}
        <div
          style={{
            position: 'relative',
            width: 110,
            height: 78,
            overflow: 'hidden',
            background: 'var(--surface3)',
          }}
        >
          <img
            src={image.url}
            alt={`Manual page ${image.page_number + 1} thumbnail`}
            width={110}
            height={142}
            loading="lazy"
            style={{
              width: '100%',
              height: 'auto',
              display: 'block',
              objectFit: 'cover',
              objectPosition: 'top',
              filter: hovered ? 'brightness(1.05)' : 'brightness(0.9)',
              transition: 'filter 0.15s',
            }}
          />
          {image.highlight && (
            <HighlightOverlay highlight={image.highlight} compact />
          )}
        </div>

        {/* Label */}
        <div
          style={{
            padding: '4px 6px',
            background: hovered ? 'var(--surface2)' : 'var(--surface)',
            borderTop: '1px solid var(--border)',
            transition: 'background 0.15s',
          }}
        >
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 9,
              color: hovered ? 'var(--accent)' : 'var(--text-muted)',
              letterSpacing: '0.04em',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              display: 'block',
              transition: 'color 0.15s',
            }}
          >
            {pageLabel}
          </span>
        </div>
      </button>

      {modalOpen && (
        <ImageModal image={image} onClose={() => setModalOpen(false)} />
      )}
    </>
  )
}
