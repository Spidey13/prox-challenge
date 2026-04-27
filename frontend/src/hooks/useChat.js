import { useState, useRef, useCallback } from 'react'
import { DEFAULT_PRODUCT_ID } from '../products'

function generateId() {
  return typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2)
}

// agentPhase: 'idle' | 'thinking' | 'streaming'
// 'thinking'  — request sent, waiting for first token
// 'streaming' — first token received, text arriving
// 'idle'      — done event received

/** Read a File object as a base64 data string (without the data-URL prefix). */
function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      // result is "data:<mime>;base64,<data>" — strip the prefix
      const result = reader.result
      const base64 = result.split(',')[1]
      resolve(base64)
    }
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

export function useChat(productId = DEFAULT_PRODUCT_ID) {
  const [messages, setMessages] = useState([])
  const [agentPhase, setAgentPhase] = useState('idle')
  const [currentArtifact, setCurrentArtifact] = useState(null)
  const [pinnedArtifact, setPinnedArtifact] = useState(null)
  const [currentJobCard, setCurrentJobCard] = useState(null)
  const conversationId = useRef(generateId())
  const abortRef = useRef(null)
  const thinkingStartRef = useRef(null)

  /**
   * sendMessage(text, imageFile?)
   *
   * imageFile — optional File object from <input type="file">
   *   - encoded as base64 and sent to /ask as image_data + image_media_type
   *   - a preview URL is stored on the user message for inline display
   */
  const sendMessage = useCallback(async (text, imageFile = null) => {
    if (!text.trim() || agentPhase !== 'idle') return

    // Encode the image (if any) before updating state
    let imageData = null
    let imageMediaType = null
    let imagePreviewUrl = null

    if (imageFile) {
      try {
        imageData = await readFileAsBase64(imageFile)
        imageMediaType = imageFile.type || 'image/jpeg'
        imagePreviewUrl = URL.createObjectURL(imageFile)
      } catch (err) {
        console.warn('Failed to read image file:', err)
      }
    }

    const userMsg = {
      role: 'user',
      content: text,
      imagePreviewUrl,   // shown inline in the user bubble
    }
    const assistantMsg = {
      role: 'assistant',
      content: '',
      suggestions: [],
      images: [],
      artifact: null,    // stored per-message for artifact history
      done: false,
    }

    setMessages(prev => [...prev, userMsg, assistantMsg])
    setAgentPhase('thinking')
    setCurrentJobCard(null)
    thinkingStartRef.current = Date.now()

    let accumulated = ''
    let firstToken = true

    try {
      const controller = new AbortController()
      abortRef.current = controller

      const body = {
        message: text,
        product_id: productId,
        conversation_id: conversationId.current,
      }
      if (imageData) {
        body.image_data = imageData
        body.image_media_type = imageMediaType
      }

      const res = await fetch('/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal,
      })

      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      const reader = res.body.getReader()
      const decoder = new TextDecoder()

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const chunk = decoder.decode(value, { stream: true })
        const lines = chunk.split('\n')

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (!raw) continue

          let event
          try { event = JSON.parse(raw) } catch { continue }

          if (event.type === 'token') {
            if (firstToken) {
              firstToken = false
              setAgentPhase('streaming')
            }
            accumulated += event.content
            setMessages(prev => {
              const updated = [...prev]
              const last = updated[updated.length - 1]
              updated[updated.length - 1] = { ...last, content: accumulated }
              return updated
            })
          } else if (event.type === 'job_card_start') {
            if (firstToken) {
              firstToken = false
              setAgentPhase('streaming')
            }
            setCurrentJobCard({ metadata: event.metadata, steps: [] })
          } else if (event.type === 'job_card_step') {
            setCurrentJobCard(prev => ({
              ...prev,
              steps: [...(prev?.steps ?? []), event.step],
            }))
          } else if (event.type === 'done') {
            const newArtifact = event.artifact ?? null

            // Only replace the displayed artifact if nothing is pinned
            if (newArtifact && !pinnedArtifact) {
              setCurrentArtifact(newArtifact)
            }

            setMessages(prev => {
              const updated = [...prev]
              const last = updated[updated.length - 1]
              updated[updated.length - 1] = {
                ...last,
                content: accumulated,
                suggestions: event.suggestions || [],
                images: event.images || [],
                artifact: newArtifact,  // stored for history restoration
                done: true,
              }
              return updated
            })
            setAgentPhase('idle')
          }
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setMessages(prev => {
          const updated = [...prev]
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            content: 'Something went wrong. Please try again.',
            done: true,
          }
          return updated
        })
      }
      setAgentPhase('idle')
    }
  }, [agentPhase, productId, pinnedArtifact])

  /** Restore an artifact from a previous message into the right panel. */
  const viewArtifact = useCallback((artifact) => {
    setCurrentArtifact(artifact)
    setPinnedArtifact(null)  // un-pin when user explicitly picks one to view
  }, [])

  const pinArtifact = useCallback(() => {
    setPinnedArtifact(currentArtifact)
  }, [currentArtifact])

  const unpinArtifact = useCallback(() => {
    setPinnedArtifact(null)
  }, [])

  const thinkingStart = thinkingStartRef.current

  return {
    messages,
    agentPhase,
    currentArtifact,
    pinnedArtifact,
    currentJobCard,
    thinkingStart,
    sendMessage,
    viewArtifact,
    pinArtifact,
    unpinArtifact,
  }
}
