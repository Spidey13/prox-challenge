import { useEffect, useRef } from 'react'
import ProductHeader from './ProductHeader'
import EmptyState from './EmptyState'
import AgentStatus from './AgentStatus'
import MessageBubble from './MessageBubble'
import SuggestionChips from './SuggestionChips'
import ChatInput from './ChatInput'

export default function ChatPanel({
  messages,
  agentPhase,
  thinkingStart,
  onSend,
  onViewArtifact,
  productId,
}) {
  const bottomRef = useRef(null)
  const listRef = useRef(null)

  const isEmpty = messages.length === 0
  const isStreaming = agentPhase !== 'idle'

  // Find last assistant message suggestions
  const lastAssistant = [...messages].reverse().find(m => m.role === 'assistant' && m.done)
  const suggestions = lastAssistant?.suggestions ?? []

  // Auto-scroll on new content
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages])

  return (
    <div
      style={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--bg)',
        overflow: 'hidden',
      }}
    >
      <ProductHeader productId={productId} />

      {/* Message list or empty state */}
      <div
        ref={listRef}
        role="log"
        aria-live="polite"
        aria-label="Conversation"
        style={{
          flex: 1,
          overflowY: 'auto',
          overflowX: 'hidden',
          padding: isEmpty ? 0 : '20px 20px 8px',
          display: 'flex',
          flexDirection: 'column',
          gap: 20,
        }}
      >
        {isEmpty ? (
          <EmptyState onSend={onSend} />
        ) : (
          <>
            {messages.map((msg, i) => (
              <MessageBubble
                key={i}
                message={msg}
                onViewArtifact={onViewArtifact}
              />
            ))}

            {/* Agent status — shows during thinking phase */}
            {agentPhase === 'thinking' && (
              <AgentStatus agentPhase={agentPhase} thinkingStart={thinkingStart} />
            )}

            <div ref={bottomRef} aria-hidden="true" />
          </>
        )}
      </div>

      {/* Suggestion chips — when not empty and not streaming */}
      {!isEmpty && suggestions.length > 0 && !isStreaming && (
        <SuggestionChips suggestions={suggestions} onSend={onSend} />
      )}

      {/* Input */}
      <ChatInput onSend={onSend} disabled={isStreaming} />
    </div>
  )
}
