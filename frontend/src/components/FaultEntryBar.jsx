import { useRef, useState, useEffect } from 'react'

export default function FaultEntryBar({ onSend, agentPhase }) {
  const [text, setText] = useState('')
  const [attachedImage, setAttachedImage] = useState(null) // { file, previewUrl }
  const inputRef = useRef(null)
  const fileInputRef = useRef(null)
  const isLoading = agentPhase !== 'idle'

  // Auto-focus input on mount
  useEffect(() => { inputRef.current?.focus() }, [])

  function handleSubmit(e) {
    e?.preventDefault()
    const trimmed = text.trim()
    if (!trimmed || isLoading) return
    onSend(trimmed, attachedImage?.file ?? null)
    setText('')
    if (attachedImage?.previewUrl) URL.revokeObjectURL(attachedImage.previewUrl)
    setAttachedImage(null)
  }

  function handleFileChange(e) {
    const file = e.target.files?.[0]
    if (!file) return
    if (attachedImage?.previewUrl) URL.revokeObjectURL(attachedImage.previewUrl)
    setAttachedImage({ file, previewUrl: URL.createObjectURL(file) })
    e.target.value = ''
    inputRef.current?.focus()
  }

  const canSend = !!text.trim() && !isLoading

  return (
    <form
      onSubmit={handleSubmit}
      style={{
        background: '#f3ede1',
        borderBottom: '1px solid #d9cfba',
        padding: '0 24px',
        flexShrink: 0,
        position: 'relative',
        zIndex: 1,
      }}
    >
      {/* Image preview strip */}
      {attachedImage && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '8px 0 0',
        }}>
          <img
            src={attachedImage.previewUrl}
            alt="Attached"
            style={{
              width: 44, height: 32, objectFit: 'cover',
              borderRadius: 6, border: '1px solid #d9cfba',
            }}
          />
          <span style={{
            flex: 1, fontFamily: "'Geist Mono', monospace", fontSize: 11,
            color: '#8a8275', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {attachedImage.file.name}
          </span>
          <button
            type="button"
            onClick={() => {
              URL.revokeObjectURL(attachedImage.previewUrl)
              setAttachedImage(null)
            }}
            style={{
              background: 'none', border: 'none', color: '#8a8275',
              cursor: 'pointer', fontSize: 14, padding: '2px 4px',
            }}
          >✕</button>
        </div>
      )}

      {/* Main row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 0' }}>
        {/* Brand mark */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0,
        }}>
          <div style={{
            width: 34, height: 34, borderRadius: '50%',
            background: '#1d1a15', color: '#f3ede1',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 19, fontWeight: 500, fontStyle: 'italic',
            letterSpacing: '-0.02em',
          }}>D</div>
          <div style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 17, fontWeight: 400, letterSpacing: '-0.02em',
            color: '#1d1a15', whiteSpace: 'nowrap',
          }}>
            Diagnost<em style={{ fontStyle: 'italic', fontWeight: 300, color: '#5a5245' }}>iq</em>
          </div>
        </div>

        {/* Divider */}
        <div style={{ width: 1, height: 26, background: '#d9cfba', flexShrink: 0 }} />

        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*,.pdf"
          onChange={handleFileChange}
          style={{ display: 'none' }}
        />

        {/* Attach button */}
        <button
          type="button"
          disabled={isLoading}
          onClick={() => fileInputRef.current?.click()}
          title="Attach image or PDF"
          style={{
            background: attachedImage ? '#fbe9d9' : 'transparent',
            border: `1px solid ${attachedImage ? '#d96b2e' : '#d9cfba'}`,
            borderRadius: 8,
            padding: '6px 10px',
            color: attachedImage ? '#d96b2e' : '#8a8275',
            cursor: isLoading ? 'not-allowed' : 'pointer',
            fontSize: 15,
            lineHeight: 1,
            flexShrink: 0,
            transition: 'background .15s, color .15s, border-color .15s',
          }}
          aria-label="Attach image or PDF"
        >
          📎
        </button>

        {/* Text input */}
        <input
          ref={inputRef}
          type="text"
          value={text}
          onChange={e => setText(e.target.value)}
          disabled={isLoading}
          placeholder={
            attachedImage
              ? 'Describe the issue shown in the image or PDF…'
              : 'Describe a fault or ask about settings, wiring, specs…'
          }
          style={{
            flex: 1,
            background: 'transparent',
            border: 'none',
            outline: 'none',
            fontFamily: "'Geist', system-ui, sans-serif",
            fontSize: 15,
            color: '#1d1a15',
            lineHeight: 1.5,
            minWidth: 0,
          }}
        />

        {/* Loading dots */}
        {isLoading && (
          <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexShrink: 0 }}>
            {[0,1,2].map(i => (
              <div key={i} style={{
                width: 5, height: 5, borderRadius: '50%', background: '#d96b2e',
                animation: `jc-blip 1.2s ease-in-out ${i * 0.18}s infinite`,
              }} />
            ))}
          </div>
        )}

        {/* Send button */}
        <button
          type="submit"
          disabled={!canSend}
          aria-label="Send"
          style={{
            width: 38, height: 38, borderRadius: '50%',
            background: canSend ? '#1d1a15' : '#e8e0d0',
            border: 'none',
            color: canSend ? '#f3ede1' : '#8a8275',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            cursor: canSend ? 'pointer' : 'default',
            transition: 'background .2s, color .2s',
            flexShrink: 0,
          }}
        >
          <svg width="15" height="15" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 10h12M12 5l5 5-5 5"/>
          </svg>
        </button>
      </div>
    </form>
  )
}
