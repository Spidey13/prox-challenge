import { useMemo } from 'react'
import { marked } from 'marked'
import ArtifactPanel from './ArtifactPanel'

marked.setOptions({ breaks: true, gfm: true })

const PAPER = '#f3ede1'
const INK   = '#1d1a15'
const INK2  = '#5a5245'
const INK3  = '#8a8275'
const LINE  = '#d9cfba'
const ACCENT = '#d96b2e'

function stripSuggestions(content) {
  if (!content) return { text: '', suggestions: [] }
  const idx = content.indexOf('---SUGGESTIONS---')
  if (idx === -1) return { text: content, suggestions: [] }
  const block = content.slice(idx)
  const lines = block.split('\n').slice(1)
  const suggestions = lines
    .map(l => l.replace(/^[-*]\s*/, '').trim())
    .filter(l => l && !l.startsWith('---'))
  return { text: content.slice(0, idx).trimEnd(), suggestions }
}

function ThinkingDots() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '20px 0' }}>
      {[0,1,2].map(i => (
        <div key={i} style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: ACCENT,
          animation: `jc-blip 1.2s ease-in-out ${i * 0.18}s infinite`,
        }} />
      ))}
      <span style={{
        fontFamily: "'Geist Mono', monospace",
        fontSize: 11,
        color: INK3,
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
        marginLeft: 4,
      }}>
        Working…
      </span>
    </div>
  )
}

function MarkdownText({ content }) {
  const html = useMemo(() => content ? marked.parse(content) : '', [content])
  if (!html) return null
  return (
    <div
      className="ra-markdown"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

export default function ResultArea({
  message,
  artifact,
  agentPhase,
  isPinned,
  onPin,
  onUnpin,
  onSend,
}) {
  const { text: cleanContent, suggestions: parsedSuggestions } = useMemo(
    () => stripSuggestions(message?.content ?? ''),
    [message?.content]
  )
  const suggestions = message?.suggestions?.length
    ? message.suggestions
    : parsedSuggestions

  const hasContent = cleanContent || agentPhase !== 'idle'
  const hasArtifact = !!artifact

  if (!hasContent && !hasArtifact) {
    return (
      <div style={{
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: PAPER,
        padding: 40,
      }}>
        <div style={{ textAlign: 'center', maxWidth: 400 }}>
          <div style={{
            width: 64,
            height: 64,
            borderRadius: '50%',
            background: '#e8e0d0',
            border: `1px solid ${LINE}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            margin: '0 auto 20px',
          }}>
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke={INK3} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
              <line x1="8" y1="13" x2="16" y2="13"/>
              <line x1="8" y1="17" x2="12" y2="17"/>
            </svg>
          </div>
          <div style={{
            fontFamily: "'Fraunces', Georgia, serif",
            fontSize: 22,
            fontWeight: 350,
            color: INK2,
            letterSpacing: '-0.02em',
            marginBottom: 8,
            fontVariationSettings: '"opsz" 144, "SOFT" 50',
          }}>
            Ask anything
          </div>
          <div style={{
            fontFamily: "'Geist', system-ui, sans-serif",
            fontSize: 14,
            color: INK3,
            lineHeight: 1.6,
          }}>
            Describe a fault for a diagnostic job card, or ask about settings, wiring, and specs.
          </div>
        </div>
      </div>
    )
  }

  // With artifact: split layout
  if (hasArtifact) {
    return (
      <div style={{
        flex: 1,
        display: 'flex',
        minHeight: 0,
        background: PAPER,
      }}>
        {cleanContent && (
          <div style={{
            width: 340,
            flexShrink: 0,
            padding: '28px 28px',
            borderRight: `1px solid ${LINE}`,
            overflowY: 'auto',
          }}>
            {agentPhase === 'thinking' && <ThinkingDots />}
            <MarkdownText content={cleanContent} />
          </div>
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <ArtifactPanel
            artifact={artifact}
            agentPhase={agentPhase}
            isPinned={isPinned}
            onPin={onPin}
            onUnpin={onUnpin}
          />
        </div>
      </div>
    )
  }

  // Text-only response
  return (
    <div style={{
      flex: 1,
      display: 'flex',
      justifyContent: 'center',
      background: PAPER,
      overflowY: 'auto',
      padding: '40px 32px',
    }}>
      <div style={{ maxWidth: 680, width: '100%' }}>
        {agentPhase === 'thinking' && <ThinkingDots />}
        {cleanContent && (
          <div>
            <MarkdownText content={cleanContent} />
            {suggestions.length > 0 && (
              <div style={{
                marginTop: 28,
                paddingTop: 20,
                borderTop: `1px solid ${LINE}`,
                display: 'flex',
                flexWrap: 'wrap',
                gap: 8,
              }}>
                {suggestions.map((s, i) => (
                  <button
                    key={i}
                    onClick={() => onSend?.(s)}
                    style={{
                      fontFamily: "'Geist', system-ui, sans-serif",
                      fontSize: 13,
                      color: INK2,
                      background: '#e8e0d0',
                      border: `1px solid ${LINE}`,
                      borderRadius: 100,
                      padding: '6px 14px',
                      lineHeight: 1.4,
                      cursor: 'pointer',
                      transition: 'background 0.15s, border-color 0.15s',
                    }}
                    onMouseEnter={e => {
                      e.currentTarget.style.background = '#ddd4c0'
                      e.currentTarget.style.borderColor = '#c8bda8'
                    }}
                    onMouseLeave={e => {
                      e.currentTarget.style.background = '#e8e0d0'
                      e.currentTarget.style.borderColor = LINE
                    }}
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
