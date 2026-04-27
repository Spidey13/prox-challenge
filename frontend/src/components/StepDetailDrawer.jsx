import { useEffect, useRef, useState } from 'react'

const BG      = '#f3ede1'
const BG2     = '#ece5d5'
const INK     = '#1d1a15'
const INK2    = '#5a5245'
const INK3    = '#8a8275'
const LINE    = '#d9cfba'
const ACCENT  = '#d96b2e'

export default function StepDetailDrawer({ step, productId, onClose }) {
  const [phase, setPhase] = useState('loading') // loading | ready | error
  const [manualImage, setManualImage] = useState(null)
  const [artifactPhase, setArtifactPhase] = useState('idle') // idle | loading | ready | error
  const [artifactHtml, setArtifactHtml] = useState(null)
  const drawerRef = useRef(null)

  // Fetch manual image on mount
  useEffect(() => {
    setPhase('loading')
    setManualImage(null)
    setArtifactHtml(null)
    setArtifactPhase('idle')

    fetch('/explain-step', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        product_id: productId,
        source_citation: step.source_citation,
        instruction: step.instruction,
      }),
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(data => {
        setManualImage(data.manual_image)
        setPhase('ready')
      })
      .catch(() => setPhase('error'))
  }, [step.id, productId, step.source_citation])

  // Lazy artifact load
  function loadArtifact() {
    setArtifactPhase('loading')
    fetch('/explain-step', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        product_id: productId,
        source_citation: step.source_citation,
        artifact_type: step.artifact_trigger?.type,
        fault_context: step.instruction,
      }),
    })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(data => {
        if (data.artifact_html) {
          setArtifactHtml(data.artifact_html)
          setArtifactPhase('ready')
        } else {
          setArtifactPhase('error')
        }
      })
      .catch(() => setArtifactPhase('error'))
  }

  // Close on Escape, focus trap
  useEffect(() => {
    function onKey(e) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    drawerRef.current?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const hasTrigger = !!step.artifact_trigger?.type

  return (
    <>
      {/* Scrim — click to close */}
      <div
        onClick={onClose}
        style={{
          position: 'absolute', inset: 0, background: 'rgba(29,26,21,0.18)',
          zIndex: 20, cursor: 'pointer',
        }}
        aria-hidden="true"
      />

      {/* Drawer panel */}
      <div
        ref={drawerRef}
        role="dialog"
        aria-label={`Source for step ${step.id}`}
        tabIndex={-1}
        style={{
          position: 'absolute', top: 0, right: 0, bottom: 0,
          width: 420,
          background: BG,
          borderLeft: `1px solid ${LINE}`,
          zIndex: 21,
          display: 'flex',
          flexDirection: 'column',
          outline: 'none',
          boxShadow: '-8px 0 32px rgba(29,26,21,0.08)',
          animation: 'jc-cardIn 0.22s ease',
        }}
      >
        {/* Drawer header */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '14px 18px 13px',
          borderBottom: `1px solid ${LINE}`,
          flexShrink: 0,
        }}>
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke={INK3} strokeWidth="1.4">
            <path d="M2 3h5a3 3 0 0 1 3 3v7a2 2 0 0 0-2-2H2V3z"/>
            <path d="M14 3H9a3 3 0 0 0-3 3v7a2 2 0 0 1 2-2h6V3z"/>
          </svg>
          <span style={{
            fontFamily: "'Geist Mono', monospace", fontSize: 10, fontWeight: 600,
            color: INK3, letterSpacing: '0.07em', textTransform: 'uppercase', flex: 1,
          }}>
            Source — Step {step.id}
          </span>
          <span style={{
            fontFamily: "'Geist Mono', monospace", fontSize: 10,
            color: ACCENT, letterSpacing: '0.04em',
          }}>
            {manualImage ? `p.${manualImage.page_number + 1}` : step.source_citation}
          </span>
          <button
            onClick={onClose}
            aria-label="Close source drawer"
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              color: INK3, fontSize: 18, lineHeight: 1, padding: '2px 4px',
              marginLeft: 6,
            }}
          >×</button>
        </div>

        {/* Scroll body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px 18px' }}>

          {/* Step instruction reminder */}
          <div style={{
            fontFamily: "'Geist', system-ui, sans-serif",
            fontSize: 13, color: INK2, lineHeight: 1.55,
            marginBottom: 18,
          }}>
            {step.instruction}
          </div>

          {/* Manual page image */}
          <div style={{
            fontFamily: "'Geist Mono', monospace", fontSize: 9, fontWeight: 600,
            color: INK3, letterSpacing: '0.07em', textTransform: 'uppercase',
            marginBottom: 8,
          }}>
            Manual page
          </div>

          {phase === 'loading' && (
            <div style={{
              height: 200, background: BG2, borderRadius: 8,
              border: `1px solid ${LINE}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <div style={{ display: 'flex', gap: 5 }}>
                {[0,1,2].map(i => (
                  <div key={i} style={{
                    width: 6, height: 6, borderRadius: '50%', background: ACCENT,
                    animation: `jc-blip 1.2s ease-in-out ${i * 0.18}s infinite`,
                  }} />
                ))}
              </div>
            </div>
          )}

          {phase === 'error' && (
            <div style={{
              height: 100, background: BG2, borderRadius: 8,
              border: `1px solid ${LINE}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontFamily: "'Geist', system-ui, sans-serif",
              fontSize: 13, color: INK3,
            }}>
              Page image unavailable
            </div>
          )}

          {phase === 'ready' && manualImage && (
            <div style={{
              position: 'relative', borderRadius: 8, overflow: 'hidden',
              border: `1px solid ${LINE}`, background: BG2,
            }}>
              <img
                src={manualImage.url}
                alt={`Manual ${step.source_citation}`}
                style={{ width: '100%', display: 'block' }}
              />
              {manualImage.highlight && (
                <div
                  aria-hidden="true"
                  style={{
                    position: 'absolute',
                    left: `${manualImage.highlight.x * 100}%`,
                    top: `${manualImage.highlight.y * 100}%`,
                    width: `${manualImage.highlight.w * 100}%`,
                    height: `${manualImage.highlight.h * 100}%`,
                    border: `2px solid ${ACCENT}`,
                    backgroundColor: 'rgba(217,107,46,0.15)',
                    borderRadius: 2,
                    pointerEvents: 'none',
                  }}
                />
              )}
            </div>
          )}

          {/* Artifact trigger section */}
          {hasTrigger && (
            <div style={{ marginTop: 24 }}>
              <div style={{
                fontFamily: "'Geist Mono', monospace", fontSize: 9, fontWeight: 600,
                color: INK3, letterSpacing: '0.07em', textTransform: 'uppercase',
                marginBottom: 10,
              }}>
                Visual reference
              </div>

              {artifactPhase === 'idle' && (
                <button
                  onClick={loadArtifact}
                  style={{
                    width: '100%', padding: '11px 16px',
                    background: BG2, border: `1px solid ${LINE}`,
                    borderRadius: 8, cursor: 'pointer',
                    display: 'flex', alignItems: 'center', gap: 8,
                    fontFamily: "'Geist', system-ui, sans-serif",
                    fontSize: 13, fontWeight: 500, color: INK2,
                    transition: 'background .15s, border-color .15s',
                    textAlign: 'left',
                  }}
                  onMouseEnter={e => {
                    e.currentTarget.style.background = '#e0d8c8'
                    e.currentTarget.style.borderColor = '#c8bda8'
                  }}
                  onMouseLeave={e => {
                    e.currentTarget.style.background = BG2
                    e.currentTarget.style.borderColor = LINE
                  }}
                >
                  <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke={ACCENT} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="3" width="14" height="14" rx="2"/>
                    <circle cx="8" cy="8" r="1.5"/>
                    <path d="M3 14l4-4 3 3 2-2 5 5"/>
                  </svg>
                  <span>{step.artifact_trigger.label ?? 'Show diagram'}</span>
                  <svg width="12" height="12" viewBox="0 0 20 20" fill="none" stroke={INK3} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginLeft: 'auto' }}>
                    <path d="M4 10h12M12 5l5 5-5 5"/>
                  </svg>
                </button>
              )}

              {artifactPhase === 'loading' && (
                <div style={{
                  height: 60, background: BG2, borderRadius: 8, border: `1px solid ${LINE}`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                  fontFamily: "'Geist', system-ui, sans-serif", fontSize: 12, color: INK3,
                }}>
                  {[0,1,2].map(i => (
                    <div key={i} style={{
                      width: 5, height: 5, borderRadius: '50%', background: ACCENT,
                      animation: `jc-blip 1.2s ease-in-out ${i * 0.18}s infinite`,
                    }} />
                  ))}
                  <span style={{ marginLeft: 4 }}>Generating diagram…</span>
                </div>
              )}

              {artifactPhase === 'error' && (
                <div style={{
                  padding: '12px 16px', background: BG2, borderRadius: 8,
                  border: `1px solid ${LINE}`,
                  fontFamily: "'Geist', system-ui, sans-serif", fontSize: 12, color: INK3,
                }}>
                  Diagram unavailable for this step.
                </div>
              )}

              {artifactPhase === 'ready' && artifactHtml && (
                <div style={{
                  borderRadius: 8, overflow: 'hidden',
                  border: `1px solid ${LINE}`,
                  height: 320,
                }}>
                  <iframe
                    srcDoc={artifactHtml}
                    title={step.artifact_trigger.label ?? 'Diagram'}
                    sandbox="allow-scripts"
                    style={{ width: '100%', height: '100%', border: 'none', display: 'block' }}
                  />
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  )
}
