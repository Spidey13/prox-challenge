import { useState, useEffect } from 'react'
import { useChat } from './hooks/useChat'
import { DEFAULT_PRODUCT_ID } from './products'
import FaultEntryBar from './components/FaultEntryBar'
import ResultArea from './components/ResultArea'
import { JobCardPanel } from './components/JobCardPanel'

export default function App() {
  const productId = DEFAULT_PRODUCT_ID
  const {
    messages,
    agentPhase,
    currentArtifact,
    pinnedArtifact,
    currentJobCard,
    sendMessage,
    pinArtifact,
    unpinArtifact,
  } = useChat(productId)

  // Hide the job card overlay when user closes it (without clearing the data)
  const [jobCardHidden, setJobCardHidden] = useState(false)

  // When a new job card arrives, always show it
  useEffect(() => {
    if (currentJobCard) setJobCardHidden(false)
  }, [currentJobCard])

  const showJobCard = !!currentJobCard && !jobCardHidden

  const displayedArtifact = pinnedArtifact ?? currentArtifact
  const lastAssistantMsg = [...messages].reverse().find(m => m.role === 'assistant') ?? null

  return (
    <div style={{
      height: '100vh',
      display: 'flex',
      flexDirection: 'column',
      background: '#f3ede1',
      overflow: 'hidden',
    }}>
      <FaultEntryBar onSend={sendMessage} agentPhase={agentPhase} />

      <ResultArea
        message={lastAssistantMsg}
        artifact={displayedArtifact}
        agentPhase={agentPhase}
        isPinned={!!pinnedArtifact}
        onPin={pinArtifact}
        onUnpin={unpinArtifact}
        onSend={sendMessage}
      />

      {showJobCard && (
        <div style={{ position: 'fixed', inset: 0, zIndex: 50 }}>
          <JobCardPanel
            jobCard={currentJobCard}
            productId={productId}
            onClose={() => setJobCardHidden(true)}
          />
        </div>
      )}
    </div>
  )
}
