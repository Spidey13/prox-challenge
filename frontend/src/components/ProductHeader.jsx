import { getProduct } from '../products'

const WeldSparkIcon = () => (
  <svg
    width="22"
    height="22"
    viewBox="0 0 24 24"
    fill="none"
    aria-hidden="true"
    style={{ flexShrink: 0 }}
  >
    {/* Welding arc / spark icon */}
    <path
      d="M12 2 L14 8 L20 6 L16 11 L22 12 L16 13 L20 18 L14 16 L12 22 L10 16 L4 18 L8 13 L2 12 L8 11 L4 6 L10 8 Z"
      fill="var(--accent)"
      opacity="0.9"
    />
    <circle cx="12" cy="12" r="3" fill="var(--bg)" />
    <circle cx="12" cy="12" r="1.5" fill="var(--accent)" />
  </svg>
)

export default function ProductHeader({ productId }) {
  const product = getProduct(productId)

  return (
    <header
      style={{
        padding: '12px 20px',
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        background: 'var(--surface)',
        flexShrink: 0,
      }}
    >
      <WeldSparkIcon />

      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontWeight: 700,
            fontSize: 14,
            color: '#e8eaf0',
            letterSpacing: '-0.02em',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {product.name}
        </div>
        <div
          style={{
            color: 'var(--text-muted)',
            fontSize: 11,
            marginTop: 1,
            fontFamily: 'var(--font-mono)',
            letterSpacing: '0.04em',
          }}
        >
          {product.tagline}
        </div>
      </div>

      {/* Process badges */}
      {product.processes.length > 0 && (
        <div
          style={{
            display: 'flex',
            gap: 4,
            flexShrink: 0,
          }}
          aria-label="Supported welding processes"
        >
          {product.processes.map(proc => (
            <span
              key={proc}
              title={`Supports ${proc} welding`}
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: '0.06em',
                padding: '2px 6px',
                borderRadius: 4,
                border: '1px solid var(--accent-border)',
                color: 'var(--accent)',
                background: 'var(--accent-dim)',
                userSelect: 'none',
              }}
            >
              {proc}
            </span>
          ))}
        </div>
      )}
    </header>
  )
}
