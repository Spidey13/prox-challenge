import { useRef, useState } from 'react'

export default function ChatInput({ onSend, disabled }) {
  const inputRef = useRef(null)
  const fileInputRef = useRef(null)
  const [focused, setFocused] = useState(false)
  const [value, setValue] = useState('')
  const [attachedImage, setAttachedImage] = useState(null) // { file, previewUrl }

  function handleSubmit(e) {
    e.preventDefault()
    const text = value.trim()
    if (!text || disabled) return
    onSend(text, attachedImage?.file ?? null)
    setValue('')
    // Release object URL and clear attachment
    if (attachedImage?.previewUrl) URL.revokeObjectURL(attachedImage.previewUrl)
    setAttachedImage(null)
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  function handleFileChange(e) {
    const file = e.target.files?.[0]
    if (!file) return
    // Release previous preview URL
    if (attachedImage?.previewUrl) URL.revokeObjectURL(attachedImage.previewUrl)
    setAttachedImage({ file, previewUrl: URL.createObjectURL(file) })
    // Reset file input so same file can be re-selected
    e.target.value = ''
  }

  function handleRemoveImage() {
    if (attachedImage?.previewUrl) URL.revokeObjectURL(attachedImage.previewUrl)
    setAttachedImage(null)
  }

  const canSend = value.trim() && !disabled

  return (
    <form
      onSubmit={handleSubmit}
      style={{
        padding: attachedImage ? '8px 16px 12px' : '12px 16px',
        borderTop: '1px solid var(--border)',
        background: 'var(--surface)',
        flexShrink: 0,
      }}
    >
      {/* Image preview strip */}
      {attachedImage && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            marginBottom: 8,
            padding: '6px 10px',
            background: 'var(--surface2)',
            border: '1px solid var(--border-bright)',
            borderRadius: 8,
            animation: 'fade-in 0.15s ease',
          }}
        >
          <img
            src={attachedImage.previewUrl}
            alt="Attached image preview"
            style={{
              width: 48,
              height: 36,
              objectFit: 'cover',
              borderRadius: 4,
              border: '1px solid var(--border)',
              flexShrink: 0,
            }}
          />
          <span
            style={{
              flex: 1,
              fontSize: 11,
              fontFamily: 'var(--font-mono)',
              color: 'var(--text-muted)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {attachedImage.file.name}
          </span>
          <button
            type="button"
            onClick={handleRemoveImage}
            aria-label="Remove attached image"
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-dim)',
              cursor: 'pointer',
              fontSize: 14,
              lineHeight: 1,
              padding: '2px 4px',
              borderRadius: 4,
              flexShrink: 0,
            }}
          >
            ✕
          </button>
        </div>
      )}

      {/* Input row */}
      <div style={{ display: 'flex', gap: 8 }}>
        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          aria-label="Attach image"
          onChange={handleFileChange}
          style={{ display: 'none' }}
          id="image-file-input"
        />

        {/* Attach button */}
        <button
          type="button"
          disabled={disabled}
          onClick={() => fileInputRef.current?.click()}
          aria-label="Attach an image"
          title="Attach an image of your weld or machine"
          style={{
            background: attachedImage ? 'var(--accent-dim)' : 'var(--surface2)',
            border: `1px solid ${attachedImage ? 'var(--accent-border)' : 'var(--border-bright)'}`,
            borderRadius: 10,
            padding: '10px 12px',
            color: attachedImage ? 'var(--accent)' : 'var(--text-dim)',
            fontSize: 16,
            cursor: disabled ? 'not-allowed' : 'pointer',
            transition: 'background 0.15s, color 0.15s, border-color 0.15s',
            flexShrink: 0,
            lineHeight: 1,
          }}
        >
          📎
        </button>

        {/* Text input wrapper */}
        <div
          style={{
            flex: 1,
            display: 'flex',
            alignItems: 'center',
            background: 'var(--surface2)',
            border: `1px solid ${focused ? 'var(--accent-border)' : 'var(--border-bright)'}`,
            borderRadius: 10,
            transition: 'border-color 0.15s, box-shadow 0.15s',
            boxShadow: focused ? '0 0 0 2px var(--accent-glow)' : 'none',
            overflow: 'hidden',
          }}
        >
          <input
            ref={inputRef}
            type="text"
            name="message"
            autoComplete="off"
            spellCheck={false}
            value={value}
            onChange={e => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            placeholder={
              attachedImage
                ? 'Describe the issue shown in the image…'
                : 'Ask about duty cycles, polarity, troubleshooting…'
            }
            disabled={disabled}
            aria-label="Message input"
            style={{
              flex: 1,
              background: 'none',
              border: 'none',
              outline: 'none',
              padding: '10px 14px',
              color: disabled ? 'var(--text-muted)' : 'var(--text)',
              fontSize: 14,
              fontFamily: 'var(--font-sans)',
              touchAction: 'manipulation',
              WebkitTapHighlightColor: 'transparent',
            }}
          />
        </div>

        {/* Send button */}
        <button
          type="submit"
          disabled={!canSend}
          aria-label="Send message"
          style={{
            background: canSend ? 'var(--accent)' : 'var(--surface3)',
            color: canSend ? '#111' : 'var(--text-dim)',
            border: 'none',
            borderRadius: 10,
            padding: '10px 18px',
            fontWeight: 700,
            fontFamily: 'var(--font-mono)',
            fontSize: 13,
            cursor: canSend ? 'pointer' : 'not-allowed',
            transition: 'background 0.15s, color 0.15s, box-shadow 0.15s',
            boxShadow: canSend ? '0 0 8px var(--accent-glow)' : 'none',
            flexShrink: 0,
            letterSpacing: '0.02em',
            touchAction: 'manipulation',
            WebkitTapHighlightColor: 'transparent',
          }}
        >
          Send
        </button>
      </div>
    </form>
  )
}
