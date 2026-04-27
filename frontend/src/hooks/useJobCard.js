import { useState, useEffect, useCallback } from 'react'

/**
 * Branching state machine for job card execution.
 *
 * jobCard — assembled object from useChat's currentJobCard:
 *   { metadata: {...}, steps: [{id, instruction, yes_next, no_next, ...}] }
 */
export function useJobCard(jobCard) {
  const [status, setStatus] = useState('loading')   // 'loading'|'active'|'escalated'|'complete'
  const [currentStepId, setCurrentStepId] = useState(null)
  const [history, setHistory] = useState([])         // [{stepId, choice, ts}]
  const [openedAt, setOpenedAt] = useState(null)
  const [elapsed, setElapsed] = useState(0)
  const [branchModalOpen, setBranchModalOpen] = useState(false)

  const steps = jobCard?.steps ?? []
  const metadata = jobCard?.metadata ?? null

  // Transition to active when first step arrives
  useEffect(() => {
    if (status === 'loading' && steps.length > 0) {
      setStatus('active')
      setCurrentStepId(steps[0].id)
      const now = Date.now()
      setOpenedAt(now)
    }
  }, [steps.length, status])

  // Live timer — ticks every second while active
  useEffect(() => {
    if (status !== 'active' || openedAt === null) return
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - openedAt) / 1000))
    }, 1000)
    return () => clearInterval(id)
  }, [status, openedAt])

  const currentStep = steps.find(s => s.id === currentStepId) ?? null

  const _advance = useCallback((choice) => {
    if (!currentStep) return

    const next = choice === 'yes' ? currentStep.yes_next : currentStep.no_next
    const stepId = currentStep.id
    const ts = Date.now()

    setHistory(prev => [...prev, { stepId, choice, ts }])

    if (next === 'complete') {
      setStatus('complete')
    } else if (next === 'escalate') {
      setStatus('escalated')
    } else if (typeof next === 'number') {
      const targetExists = steps.some(s => s.id === next)
      if (targetExists) {
        setCurrentStepId(next)
      }
      // If the step hasn't arrived yet via SSE, stay on current step
    }
  }, [currentStep, steps])

  const answerYes = useCallback(() => _advance('yes'), [_advance])

  // answerNo opens the branch modal instead of advancing immediately
  const answerNo = useCallback(() => {
    setBranchModalOpen(true)
  }, [])

  // Called when user confirms the branch warning
  const confirmBranchAndAdvance = useCallback(() => {
    setBranchModalOpen(false)
    _advance('no')
  }, [_advance])

  const dismissBranch = useCallback(() => {
    setBranchModalOpen(false)
  }, [])

  // Whether the next step for a given choice has arrived yet (for button gating)
  const isYesReady = currentStep
    ? currentStep.yes_next === 'complete' || typeof currentStep.yes_next !== 'number'
      || steps.some(s => s.id === currentStep.yes_next)
    : false

  const isNoReady = currentStep
    ? currentStep.no_next === 'escalate' || typeof currentStep.no_next !== 'number'
      || steps.some(s => s.id === currentStep.no_next)
    : false

  const completedSteps = steps.filter(s => history.some(h => h.stepId === s.id))

  return {
    status,
    metadata,
    steps,
    currentStep,
    completedSteps,
    history,
    elapsed,
    isYesReady,
    isNoReady,
    answerYes,
    answerNo,
    branchModalOpen,
    confirmBranchAndAdvance,
    dismissBranch,
  }
}
