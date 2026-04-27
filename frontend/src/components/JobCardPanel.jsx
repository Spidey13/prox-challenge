import { useRef, useEffect, useCallback, useState } from 'react'
import { useJobCard } from '../hooks/useJobCard'
import StepDetailDrawer from './StepDetailDrawer'
import { getProduct } from '../products'
import './JobCard.css'

/* ─── HELPERS ─── */

function simpleHash(str) {
  let h = 0
  for (let i = 0; i < str.length; i++) h = Math.imul(31, h) + str.charCodeAt(i) | 0
  return Math.abs(h)
}

function formatTimer(s) {
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`
  return `${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`
}

// Parse <em>…</em> tags into React elements
function withEm(str) {
  if (!str) return str
  const parts = String(str).split(/(<em>.*?<\/em>)/g)
  return parts.map((p, i) => {
    const m = p.match(/^<em>(.*?)<\/em>$/)
    return m
      ? <em key={i}>{m[1]}</em>
      : <span key={i}>{p}</span>
  })
}

const PRIORITY_COLORS = {
  LOW:      '#5c7a54',
  MEDIUM:   '#d96b2e',
  HIGH:     '#b84d14',
  CRITICAL: '#8a2a14',
}

const RING_R = 26
const RING_C = 2 * Math.PI * RING_R // ≈163.4

/* ─── SUB-COMPONENTS ─── */

function StatusPill({ status }) {
  const labels = {
    loading:   'Generating',
    active:    'In Progress',
    escalated: 'Escalated',
    complete:  'Complete',
  }
  return (
    <div className="jc-status-row">
      <div className="jc-status-pill">
        <div className="jc-dot" />
        {labels[status] ?? status}
      </div>
    </div>
  )
}

function FaultHeadline({ metadata }) {
  if (!metadata) return null
  const words = (metadata.fault_description || '').split(' ')
  // Italicise the last 2 words for editorial effect
  const plain = words.slice(0, -2).join(' ')
  const italic = words.slice(-2).join(' ')
  return (
    <div>
      <div className="jc-fault-title">
        {plain} <em>{italic}</em>
      </div>
      <div className="jc-fault-sub">{metadata.equipment}</div>
    </div>
  )
}

function DataLedger({ metadata }) {
  if (!metadata) return null
  const priority = metadata.priority ?? 'MEDIUM'
  const priorityColor = PRIORITY_COLORS[priority] ?? '#d96b2e'
  return (
    <div className="jc-ledger">
      <div className="jc-ledger-cell">
        <div className="jc-ledger-label">Asset ID</div>
        <div className="jc-ledger-value mono">{metadata.asset_id || '—'}</div>
      </div>
      <div className="jc-ledger-cell">
        <div className="jc-ledger-label">Priority</div>
        <div className="jc-ledger-value">
          <span
            className="jc-priority"
            style={{ background: priorityColor }}
          >
            {priority}
          </span>
        </div>
      </div>
      <div className="jc-ledger-cell">
        <div className="jc-ledger-label">Equipment</div>
        <div className="jc-ledger-value">{metadata.equipment || '—'}</div>
      </div>
      <div className="jc-ledger-cell">
        <div className="jc-ledger-label">Status</div>
        <div className="jc-ledger-value mono">{metadata.priority === 'CRITICAL' ? 'Urgent' : 'Active'}</div>
      </div>
    </div>
  )
}

function ProgressRing({ completed, total, status }) {
  const progress = total > 0 ? completed / total : 0
  const offset = RING_C * (1 - progress)
  const strokeColor = status === 'escalated' ? '#c0381b' : status === 'complete' ? '#5c7a54' : '#d96b2e'
  return (
    <div className="jc-progress-ring">
      <svg width="56" height="56" viewBox="0 0 56 56">
        <circle className="jc-ring-bg" cx="28" cy="28" r={RING_R} />
        <circle
          className="jc-ring-fg"
          cx="28" cy="28" r={RING_R}
          style={{
            stroke: strokeColor,
            strokeDasharray: RING_C,
            strokeDashoffset: offset,
            strokeLinecap: 'round',
            transform: 'rotate(-90deg)',
            transformOrigin: '28px 28px',
          }}
        />
      </svg>
      <div className="jc-ring-num">{completed}/{total}</div>
    </div>
  )
}

function TimerCard({ elapsed, completedSteps, steps, status }) {
  return (
    <div className="jc-timer-card">
      <div>
        <div className="jc-timer-label">Elapsed</div>
        <div className="jc-timer-value">{formatTimer(elapsed)}</div>
      </div>
      <ProgressRing
        completed={completedSteps.length}
        total={Math.max(steps.length, 1)}
        status={status}
      />
    </div>
  )
}

function CompletedList({ completedSteps, history }) {
  if (completedSteps.length === 0) return null
  return (
    <div className="jc-completed-section">
      <div className="jc-completed-header">
        <div className="jc-completed-title">Record</div>
        <div className="jc-completed-count">{completedSteps.length} step{completedSteps.length !== 1 ? 's' : ''}</div>
      </div>
      <div className="jc-completed-list">
        {completedSteps.map(step => {
          const record = history.find(h => h.stepId === step.id)
          const choice = record?.choice ?? 'yes'
          return (
            <div key={step.id} className="jc-completed-item">
              <div className="jc-completed-num">
                {String(step.id).padStart(2, '0')}
              </div>
              <div className="jc-completed-text">
                {step.instruction}
              </div>
              <div>
                <span className={`jc-result-chip ${choice === 'yes' ? 'y' : 'n'}`}>
                  <span className="jc-chip-dot" />
                  {choice === 'yes' ? 'Pass' : 'Fail'}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function StepNav({ currentStep, completedSteps, steps }) {
  const completedIds = new Set(completedSteps.map(s => s.id))
  return (
    <>
      <div className="jc-step-nav">
        <span className="jc-step-label">Diagnostic Step</span>
        <span className="jc-step-counter">
          <span className="jc-now">{currentStep?.id ?? '—'}</span>
          {' / '}{steps.length}
        </span>
      </div>
      <div className="jc-step-progress">
        {steps.map(s => {
          let cls = ''
          if (completedIds.has(s.id)) cls = 'done'
          else if (s.id === currentStep?.id) cls = 'active'
          return <div key={s.id} className={`jc-sp-seg ${cls}`} />
        })}
      </div>
    </>
  )
}

function StepCard({ step, swiperRef, handleRef, onPointerDown, onPointerMove, onPointerUp, onCiteClick }) {
  return (
    <div className="jc-step-card">
      <div className="jc-step-cat">{step.id} — Diagnostic</div>
      <div className="jc-step-q">{withEm(step.instruction)}</div>
      {step.note && <div className="jc-step-hint">{step.note}</div>}
      {step.source_citation && !step.citation_missing && (
        <button
          className="jc-step-cite"
          onClick={onCiteClick}
          title="View source in manual"
          style={{ cursor: 'pointer', background: 'none', border: 'none', padding: 0, textAlign: 'left' }}
        >
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4">
            <path d="M2 3h5a3 3 0 0 1 3 3v7a2 2 0 0 0-2-2H2V3z"/>
            <path d="M14 3H9a3 3 0 0 0-3 3v7a2 2 0 0 1 2-2h6V3z"/>
          </svg>
          Manual ref
          <span style={{ marginLeft: 4, opacity: 0.5, fontSize: '0.85em' }}>↗</span>
        </button>
      )}
      <div
        className="jc-swiper"
        ref={swiperRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <div className="jc-swipe-reveal" />
        <div className="jc-swipe-track">
          <div className="jc-track-side">
            <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M16 10H4M8 5L3 10l5 5"/>
            </svg>
            <span>{step.no_label || 'No'}</span>
          </div>
          <div className="jc-track-label">Swipe to answer</div>
          <div className="jc-track-side">
            <span>{step.yes_label || 'Yes'}</span>
            <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 10h12M12 5l5 5-5 5"/>
            </svg>
          </div>
        </div>
        <div className="jc-swipe-handle" ref={handleRef}>
          <svg width="28" height="28" viewBox="0 0 30 30" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10 15h10M14 11l-4 4 4 4M16 11l4 4-4 4"/>
          </svg>
        </div>
      </div>
      <div className="jc-swipe-hint">
        Drag or press <span className="jc-kbd">Y</span> / <span className="jc-kbd">N</span>
      </div>
    </div>
  )
}

function BranchModal({ step, onConfirm, onDismiss, escalationCopy }) {
  const isEscalate = step.no_next === 'escalate'
  const bandLabel = isEscalate
    ? (escalationCopy?.title ?? 'Escalation Required')
    : 'Fault Detected'
  const escalateText = escalationCopy?.instruction
    ?? 'This fault requires escalation. Do not proceed further.'
  return (
    <div className="jc-branch-scrim" onClick={onDismiss}>
      <div
        className={`jc-branch-card ${isEscalate ? 'esc' : ''}`}
        onClick={e => e.stopPropagation()}
      >
        <div className="jc-branch-band">
          <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10 2L2 17h16L10 2z"/>
            <path d="M10 8v4M10 14v.5"/>
          </svg>
          {bandLabel}
        </div>
        <div className="jc-branch-body">
          <div className="jc-branch-title">
            {isEscalate
              ? <>Fault detected — <em>escalate</em> to supervisor.</>
              : <>{withEm(step.instruction)} — result: <em>{step.no_label}</em>.</>
            }
          </div>
          <div className="jc-branch-text">
            {isEscalate
              ? escalateText
              : `Record the result "${step.no_label}" and follow the corrective action before continuing.`
            }
          </div>
          {isEscalate && escalationCopy?.actions?.length > 0 && (
            <ul className="jc-branch-actions-list">
              {escalationCopy.actions.map((action, i) => (
                <li key={i} className="jc-branch-action-item">{action}</li>
              ))}
            </ul>
          )}
          {step.source_citation && (
            <div className="jc-branch-ref">Ref: {step.source_citation}</div>
          )}
          <div className="jc-branch-actions">
            <button
              className={`jc-btn-primary ${isEscalate ? 'esc' : ''}`}
              onClick={onConfirm}
            >
              {isEscalate ? 'Confirm escalation' : 'Confirmed, continue'}
            </button>
            <button className="jc-btn-ghost" onClick={onDismiss}>
              Go back
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function CompletePanel({ elapsed, completedSteps, history, onClose }) {
  const faults = history.filter(h => h.choice === 'no').length
  const passes = history.filter(h => h.choice === 'yes').length
  return (
    <div className="jc-complete-panel">
      <div className="jc-complete-seal">
        <svg width="56" height="56" viewBox="0 0 30 30" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 15.5l5.5 5.5L24 8.5"/>
        </svg>
      </div>
      <div className="jc-complete-h">
        Ready for <em>return to service</em>
      </div>
      <div className="jc-complete-sub">
        All diagnostic steps completed. Review the audit record before signing off.
      </div>
      <div className="jc-complete-stats">
        <div className="jc-cstat">
          <div className="jc-cstat-v">{completedSteps.length}</div>
          <div className="jc-cstat-l">Steps</div>
        </div>
        <div className="jc-cstat">
          <div className="jc-cstat-v">{faults}</div>
          <div className="jc-cstat-l">Faults</div>
        </div>
        <div className="jc-cstat">
          <div className="jc-cstat-v">{formatTimer(elapsed)}</div>
          <div className="jc-cstat-l">Duration</div>
        </div>
      </div>
      <div className="jc-complete-cta">
        {onClose && (
          <button className="jc-btn-primary" onClick={onClose}>Close job card</button>
        )}
      </div>
    </div>
  )
}

function EscalatePanel({ currentStep, onClose, escalationCopy }) {
  const title = escalationCopy?.title ?? 'Escalation Required'
  const instruction = escalationCopy?.instruction ?? 'This fault requires supervisor intervention. Do not attempt further repair.'
  const actions = escalationCopy?.actions ?? []
  return (
    <div className="jc-complete-panel esc">
      <div className="jc-complete-seal esc">
        <svg width="56" height="56" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M10 2L2 17h16L10 2z"/>
          <path d="M10 8v4M10 14v.5"/>
        </svg>
      </div>
      <div className="jc-complete-h">
        <em>{title}</em>
      </div>
      <div className="jc-complete-sub">
        {currentStep?.no_label
          ? `Result: "${currentStep.no_label}". ${instruction}`
          : instruction
        }
      </div>
      {actions.length > 0 && (
        <ul className="jc-branch-actions-list" style={{ marginBottom: 16 }}>
          {actions.map((action, i) => (
            <li key={i} className="jc-branch-action-item">{action}</li>
          ))}
        </ul>
      )}
      {currentStep?.source_citation && (
        <div style={{ fontFamily: "'Geist Mono', monospace", fontSize: 11, color: '#8a8275', marginBottom: 24 }}>
          Ref: {currentStep.source_citation}
        </div>
      )}
      <div className="jc-complete-cta">
        {onClose && (
          <button className="jc-btn-primary esc" onClick={onClose}>Acknowledge & close</button>
        )}
      </div>
    </div>
  )
}

/* ─── MAIN COMPONENT ─── */

export function JobCardPanel({ jobCard, productId, onClose }) {
  const {
    status, metadata, steps, currentStep, completedSteps, history,
    elapsed, isYesReady, isNoReady,
    answerYes, answerNo,
    branchModalOpen, confirmBranchAndAdvance, dismissBranch,
  } = useJobCard(jobCard)

  const [detailStep, setDetailStep] = useState(null)

  // Load escalation copy from product registry
  const product = productId ? getProduct(productId) : null
  const escalationCopy = product?.escalation_copy ?? null

  const rootRef   = useRef(null)
  const swiperRef = useRef(null)
  const handleRef = useRef(null)
  const drag      = useRef({ active: false, startX: 0, currentDx: 0, maxDx: 0 })

  // Generate a short job ID from the fault description
  const jobId = metadata
    ? `JC-${String(simpleHash(metadata.fault_description || '')).slice(0, 4).padStart(4, '0')}`
    : 'JC-0000'

  // Position swipe handle at center when step changes
  useEffect(() => {
    if (!handleRef.current || !swiperRef.current) return
    const trackW = swiperRef.current.offsetWidth
    const handleW = handleRef.current.offsetWidth || 76
    handleRef.current.style.left = `${(trackW - handleW) / 2}px`
    handleRef.current.style.transform = 'translateX(0)'
    swiperRef.current.classList.remove('active-y', 'active-n')
  }, [currentStep?.id])

  // Keyboard handler
  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Escape' && detailStep) {
      setDetailStep(null)
      return
    }
    if (status !== 'active' || branchModalOpen || detailStep) return
    if (e.key === 'y' || e.key === 'Y' || e.key === 'ArrowRight') {
      if (isYesReady) answerYes()
    } else if (e.key === 'n' || e.key === 'N' || e.key === 'ArrowLeft') {
      if (isNoReady) answerNo()
    }
  }, [status, branchModalOpen, detailStep, isYesReady, isNoReady, answerYes, answerNo])

  // Auto-focus root for keyboard events
  useEffect(() => {
    rootRef.current?.focus()
  }, [])

  // Swipe pointer handlers
  const handlePointerDown = useCallback((e) => {
    if (status !== 'active') return
    e.currentTarget.setPointerCapture(e.pointerId)
    const trackW = swiperRef.current?.offsetWidth ?? 400
    const handleW = handleRef.current?.offsetWidth ?? 76
    drag.current = {
      active: true,
      startX: e.clientX,
      currentDx: 0,
      maxDx: (trackW - handleW - 12) / 2,
    }
    if (handleRef.current) handleRef.current.style.transition = 'none'
  }, [status])

  const handlePointerMove = useCallback((e) => {
    if (!drag.current.active) return
    const dx = Math.max(-drag.current.maxDx, Math.min(drag.current.maxDx, e.clientX - drag.current.startX))
    drag.current.currentDx = dx
    if (handleRef.current) {
      handleRef.current.style.transform = `translateX(${dx}px)`
    }
    const threshold = drag.current.maxDx * 0.4
    if (swiperRef.current) {
      if (dx > threshold) {
        swiperRef.current.classList.add('active-y')
        swiperRef.current.classList.remove('active-n')
      } else if (dx < -threshold) {
        swiperRef.current.classList.add('active-n')
        swiperRef.current.classList.remove('active-y')
      } else {
        swiperRef.current.classList.remove('active-y', 'active-n')
      }
    }
  }, [])

  const handlePointerUp = useCallback(() => {
    if (!drag.current.active) return
    drag.current.active = false
    const { currentDx, maxDx } = drag.current
    const threshold = maxDx * 0.4

    // Spring back
    if (handleRef.current) {
      handleRef.current.style.transition = 'transform .45s cubic-bezier(.34,1.4,.35,1)'
      handleRef.current.style.transform = 'translateX(0)'
    }
    if (swiperRef.current) {
      swiperRef.current.classList.remove('active-y', 'active-n')
    }

    if (currentDx > threshold && isYesReady) {
      answerYes()
    } else if (currentDx < -threshold && isNoReady) {
      answerNo()
    }
  }, [isYesReady, isNoReady, answerYes, answerNo])

  return (
    <div
      className="jc-root"
      ref={rootRef}
      tabIndex={0}
      onKeyDown={handleKeyDown}
      style={{ outline: 'none' }}
    >
      <div className="jc-grain" aria-hidden="true" />
      <div className="jc-radial" aria-hidden="true" />

      <div className="jc-shell">
        {/* Header */}
        <header className="jc-hdr">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div className="jc-brand-mark">D</div>
            <div className="jc-brand-name">Diagnost<em>iq</em></div>
          </div>
          <div className="jc-hdr-crumbs" style={{ justifyContent: 'center' }}>
            <span className="jc-job-code">{jobId}</span>
            <span className="jc-sep">·</span>
            <b>{metadata?.equipment ?? 'Generating…'}</b>
          </div>
          <div className="jc-hdr-actions">
            {onClose && (
              <button className="jc-iconbtn" onClick={onClose} aria-label="Close job card">
                ×
              </button>
            )}
          </div>
        </header>

        {/* Main grid */}
        <div className={`jc-grid jc-s-${status}`}>
          {/* LEFT COLUMN */}
          <div className="jc-meta-col">
            <StatusPill status={status} />
            <FaultHeadline metadata={metadata} />
            <DataLedger metadata={metadata} />
            <TimerCard
              elapsed={elapsed}
              completedSteps={completedSteps}
              steps={steps}
              status={status}
            />
            <CompletedList completedSteps={completedSteps} history={history} />
          </div>

          {/* RIGHT COLUMN */}
          <div className="jc-work-col" style={{ position: 'relative' }}>
            {status === 'loading' && (
              <div className="jc-loading">
                <div className="jc-loading-pulse" />
                <div className="jc-loading-text">Generating job card…</div>
              </div>
            )}

            {status === 'active' && currentStep && (
              <>
                <StepNav
                  currentStep={currentStep}
                  completedSteps={completedSteps}
                  steps={steps}
                />
                <StepCard
                  step={currentStep}
                  swiperRef={swiperRef}
                  handleRef={handleRef}
                  onPointerDown={handlePointerDown}
                  onPointerMove={handlePointerMove}
                  onPointerUp={handlePointerUp}
                  onCiteClick={() => setDetailStep(currentStep)}
                />
              </>
            )}

            {status === 'complete' && (
              <CompletePanel
                elapsed={elapsed}
                completedSteps={completedSteps}
                history={history}
                onClose={onClose}
              />
            )}

            {status === 'escalated' && (
              <EscalatePanel currentStep={currentStep} onClose={onClose} escalationCopy={escalationCopy} />
            )}

            {/* Step detail drawer — slides in from right inside work column */}
            {detailStep && productId && (
              <StepDetailDrawer
                step={detailStep}
                productId={productId}
                onClose={() => setDetailStep(null)}
              />
            )}
          </div>
        </div>
      </div>

      {/* Branch modal */}
      {branchModalOpen && currentStep && (
        <BranchModal
          step={currentStep}
          onConfirm={confirmBranchAndAdvance}
          onDismiss={dismissBranch}
          escalationCopy={escalationCopy}
        />
      )}
    </div>
  )
}
