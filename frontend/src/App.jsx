import { useState } from 'react'
import { useChat } from './hooks/useChat'
import { DEFAULT_PRODUCT_ID } from './products'
import ChatPanel from './components/ChatPanel'
import ArtifactPanel from './components/ArtifactPanel'

export default function App() {
  const productId = DEFAULT_PRODUCT_ID
  const {
    messages,
    agentPhase,
    thinkingStart,
    currentArtifact,
    pinnedArtifact,
    sendMessage,
    viewArtifact,
    pinArtifact,
    unpinArtifact,
  } = useChat(productId)

  // Mobile: which tab is active ('chat' | 'interactive')
  const [mobileTab, setMobileTab] = useState('chat')

  // The artifact shown in the right panel: pinned takes priority
  const displayedArtifact = pinnedArtifact ?? currentArtifact
  const hasArtifact = !!displayedArtifact
  const isStreaming = agentPhase !== 'idle'

  return (
    <div
      style={{
        display: 'flex',
        height: '100vh',
        width: '100%',
        overflow: 'hidden',
        position: 'relative',
      }}
    >
      {/* ── Desktop layout: 60/40 split ─────────────────────────── */}
      <div
        className="desktop-only"
        style={{
          display: 'flex',
          width: '100%',
          height: '100%',
        }}
      >
        {/* Chat panel — 60% */}
        <div
          style={{
            flex: '0 0 60%',
            minWidth: 0,
            height: '100%',
            borderRight: '1px solid var(--border)',
          }}
        >
          <ChatPanel
            messages={messages}
            agentPhase={agentPhase}
            thinkingStart={thinkingStart}
            onSend={sendMessage}
            onViewArtifact={viewArtifact}
            productId={productId}
          />
        </div>

        {/* Artifact panel — 40% */}
        <div style={{ flex: '0 0 40%', minWidth: 0, height: '100%' }}>
          <ArtifactPanel
            artifact={displayedArtifact}
            agentPhase={agentPhase}
            isPinned={!!pinnedArtifact}
            onPin={pinArtifact}
            onUnpin={unpinArtifact}
          />
        </div>
      </div>

      {/* ── Mobile layout: single panel + tab bar ───────────────── */}
      <div
        className="mobile-only"
        style={{
          display: 'flex',
          flexDirection: 'column',
          width: '100%',
          height: '100%',
        }}
      >
        {/* Active panel */}
        <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
          {mobileTab === 'chat' ? (
            <ChatPanel
              messages={messages}
              agentPhase={agentPhase}
              thinkingStart={thinkingStart}
              onSend={sendMessage}
              onViewArtifact={(artifact) => {
                viewArtifact(artifact)
                setMobileTab('interactive')
              }}
              productId={productId}
            />
          ) : (
            <ArtifactPanel
              artifact={displayedArtifact}
              agentPhase={agentPhase}
              isPinned={!!pinnedArtifact}
              onPin={pinArtifact}
              onUnpin={unpinArtifact}
            />
          )}
        </div>

        {/* Tab bar */}
        <div
          className="mobile-tab-bar"
          role="tablist"
          aria-label="Panel switcher"
          style={{
            borderTop: '1px solid var(--border)',
            background: 'var(--surface)',
            display: 'flex',
            flexShrink: 0,
          }}
        >
          {[
            { id: 'chat', label: 'Chat' },
            { id: 'interactive', label: hasArtifact ? '⚡ Interactive' : 'Interactive' },
          ].map(tab => (
            <button
              key={tab.id}
              role="tab"
              aria-selected={mobileTab === tab.id}
              onClick={() => setMobileTab(tab.id)}
              style={{
                flex: 1,
                padding: '13px 8px',
                background: 'none',
                border: 'none',
                borderTop: `2px solid ${mobileTab === tab.id ? 'var(--accent)' : 'transparent'}`,
                color: mobileTab === tab.id ? 'var(--accent)' : 'var(--text-muted)',
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                fontWeight: mobileTab === tab.id ? 700 : 400,
                letterSpacing: '0.06em',
                textTransform: 'uppercase',
                cursor: 'pointer',
                transition: 'color 0.15s, border-color 0.15s',
                touchAction: 'manipulation',
              }}
            >
              {tab.label}
              {tab.id === 'interactive' && isStreaming && mobileTab !== 'interactive' && (
                <span
                  aria-hidden="true"
                  style={{
                    display: 'inline-block',
                    width: 5,
                    height: 5,
                    borderRadius: '50%',
                    background: 'var(--accent)',
                    marginLeft: 5,
                    verticalAlign: 'middle',
                    animation: 'pulse-dot 1.2s ease-in-out infinite',
                  }}
                />
              )}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
