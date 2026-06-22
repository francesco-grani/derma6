import { useRef, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { Badge } from '@/components/ui/badge'
import { useProfile } from '@/hooks/useProfile'
import { useDeleteSkinAnalysis, useSkinAnalyses } from '@/hooks/useSkinAnalysis'
import { useSession } from '@/lib/sessionContext'
import { apiPatchProfile } from '@/lib/api'
import type { SkinAnalysisRecord } from '@/lib/api'

const BEARD_LABELS: Record<string, string> = {
  shave: 'Clean-shaven',
  trim:  'Trims / maintains beard',
  grow:  'Lets it grow',
}

function capitalize(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1)
}

export default function ProfilePage() {
  const { data: profile, isLoading, error } = useProfile()
  const { data: analyses } = useSkinAnalyses()
  const qc = useQueryClient()

  async function save(patch: Parameters<typeof apiPatchProfile>[0]) {
    await apiPatchProfile(patch)
    qc.invalidateQueries({ queryKey: ['profile'] })
  }

  if (isLoading) return <PageShell><p style={{ color: '#9EAD9E' }}>Loading profile…</p></PageShell>
  if (error || !profile) return <PageShell><p style={{ color: '#F0B8B8' }}>Could not load profile.</p></PageShell>

  return (
    <PageShell>
      <div style={{ maxWidth: 480 }}>
        <h2 style={{ color: '#E0E8E0', fontSize: 20, fontWeight: 700, marginBottom: 16 }}>My Profile</h2>

        <div className="grid grid-cols-2 gap-3 mb-4">
          <EditableTextCard
            label="Skin Type"
            value={profile.skin_type ?? ''}
            display={profile.skin_type ? capitalize(profile.skin_type) : '—'}
            onSave={v => save({ skin_type: v })}
          />
          <BeardStyleCard
            value={profile.beard_style ?? null}
            onSave={v => save({ beard_style: v })}
          />
          <EditableTextCard
            label="Location"
            value={profile.location ?? ''}
            display={profile.location ?? '—'}
            onSave={v => save({ location: v })}
          />
          <MetricCard label="Onboarding" value={profile.onboarding_complete ? '✅ Complete' : '⏳ In progress'} />

          <SkinConcernsCard
            concerns={profile.skin_concerns}
            onSave={concerns => save({ skin_concerns: concerns })}
          />
        </div>

        {profile.medical_flags.length > 0 && (
          <div className="mb-6 p-3 rounded-xl" style={{ background: '#5A3E3E', border: '1px solid #7A4E4E' }}>
            <p style={{ color: '#F0B8B8', fontSize: 12 }}>
              ⚠️ Medical flags: {profile.medical_flags.join(', ')}. Please consult a dermatologist before making changes to your routine.
            </p>
          </div>
        )}
      </div>

      {analyses && analyses.length > 0 && (
        <SkinAnalysisTimeline analyses={analyses} />
      )}
    </PageShell>
  )
}

function SkinAnalysisTimeline({ analyses }: { analyses: SkinAnalysisRecord[] }) {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [zoomSrc, setZoomSrc] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const navigate = useNavigate()
  const { startNewSession } = useSession()
  const deleteAnalysis = useDeleteSkinAnalysis()

  const selected = analyses.find(a => a.id === selectedId) ?? null

  async function handleChatAbout(message: string) {
    await startNewSession()
    sessionStorage.setItem('derma6:initial-message', message)
    navigate({ to: '/chat' })
  }

  async function handleDelete() {
    if (!selected) return
    if (!confirmDelete) { setConfirmDelete(true); return }
    await deleteAnalysis.mutateAsync(selected.id)
    setSelectedId(null)
    setConfirmDelete(false)
  }

  function handleSelectDot(id: number) {
    setSelectedId(prev => prev === id ? null : id)
    setConfirmDelete(false)
  }

  return (
    <div className="mb-6">
      <p className="text-xs font-semibold tracking-widest uppercase mb-4" style={{ color: '#9EAD9E' }}>
        Analysis History
      </p>

      {/* Timeline bar */}
      <div className="relative overflow-x-auto pb-6" style={{ minHeight: 80 }}>
        {/* Horizontal line */}
        <div
          style={{
            position: 'absolute',
            top: 20,
            left: 0,
            right: 0,
            height: 2,
            background: '#4B5A4C',
            minWidth: analyses.length * 72,
          }}
        />

        {/* Dots */}
        <div className="flex gap-0" style={{ minWidth: analyses.length * 72 }}>
          {analyses.map((a) => {
            const isSelected = a.id === selectedId
            const date = new Date(a.created_at)
            const label = date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
            const confidencePct = Math.round(a.confidence * 100)
            const dotColor =
              confidencePct >= 75 ? '#7A9B7D' : confidencePct >= 50 ? '#B5A55A' : '#C07070'

            return (
              <div
                key={a.id}
                className="flex flex-col items-center"
                style={{ width: 72, flexShrink: 0, cursor: 'pointer' }}
                onClick={() => handleSelectDot(a.id)}
              >
                {/* Dot */}
                <div
                  style={{
                    width: isSelected ? 20 : 14,
                    height: isSelected ? 20 : 14,
                    borderRadius: '50%',
                    background: isSelected ? dotColor : '#2E3D2F',
                    border: `2px solid ${dotColor}`,
                    boxShadow: isSelected ? `0 0 0 3px ${dotColor}33` : 'none',
                    transition: 'all 0.15s ease',
                    position: 'relative',
                    zIndex: 1,
                    marginTop: isSelected ? 11 : 14,
                  }}
                />
                {/* Thumbnail */}
                {a.thumbnail_b64 && (
                  <img
                    src={`data:image/jpeg;base64,${a.thumbnail_b64}`}
                    alt={a.condition}
                    style={{
                      width: 40,
                      height: 40,
                      borderRadius: 6,
                      objectFit: 'cover',
                      marginTop: 6,
                      border: isSelected ? `2px solid ${dotColor}` : '2px solid #4B5A4C',
                      transition: 'border-color 0.15s ease',
                    }}
                  />
                )}
                {/* Date label */}
                <span style={{ color: '#9EAD9E', fontSize: 10, marginTop: 4, whiteSpace: 'nowrap' }}>
                  {label}
                </span>
              </div>
            )
          })}
        </div>
      </div>

      {/* Detail panel */}
      {selected && (
        <div
          className="rounded-2xl p-4 flex flex-col gap-4"
          style={{ background: '#2A3A2B', border: '1px solid #4B5A4C' }}
        >
          {/* Panel header: close + delete */}
          <div className="flex justify-between items-center">
            <span style={{ color: '#9EAD9E', fontSize: 11, textTransform: 'uppercase', letterSpacing: 1 }}>
              {new Date(selected.created_at).toLocaleString(undefined, {
                month: 'long', day: 'numeric', year: 'numeric',
                hour: '2-digit', minute: '2-digit',
              })}
            </span>
            <button
              onClick={handleDelete}
              disabled={deleteAnalysis.isPending}
              style={{
                background: confirmDelete ? '#7A4E4E' : 'transparent',
                border: `1px solid ${confirmDelete ? '#C07070' : '#4B5A4C'}`,
                color: confirmDelete ? '#F0B8B8' : '#9EAD9E',
                borderRadius: 8,
                fontSize: 12,
                padding: '3px 10px',
                cursor: 'pointer',
                transition: 'all 0.15s ease',
              }}
            >
              {deleteAnalysis.isPending ? 'Deleting…' : confirmDelete ? 'Confirm delete' : 'Delete'}
            </button>
          </div>

          {/* Image + primary finding */}
          <div className="flex gap-4 flex-wrap">
            {selected.thumbnail_b64 && (
              <div style={{ position: 'relative', flexShrink: 0 }}>
                <img
                  src={`data:image/jpeg;base64,${selected.thumbnail_b64}`}
                  alt={selected.condition}
                  style={{
                    width: 120,
                    height: 120,
                    borderRadius: 12,
                    objectFit: 'cover',
                    border: '2px solid #4B5A4C',
                    cursor: selected.image_b64 ? 'zoom-in' : 'default',
                  }}
                  onClick={() => selected.image_b64 && setZoomSrc(`data:image/jpeg;base64,${selected.image_b64}`)}
                  title={selected.image_b64 ? 'Click to zoom' : undefined}
                />
                {selected.image_b64 && (
                  <span
                    style={{
                      position: 'absolute',
                      bottom: 4,
                      right: 4,
                      background: 'rgba(0,0,0,0.55)',
                      borderRadius: 4,
                      padding: '1px 4px',
                      fontSize: 10,
                      color: '#E0E8E0',
                      pointerEvents: 'none',
                    }}
                  >
                    🔍
                  </span>
                )}
              </div>
            )}

            <div className="flex flex-col gap-1" style={{ flex: 1, minWidth: 160 }}>
              <p style={{ color: '#E0E8E0', fontSize: 20, fontWeight: 700, margin: '4px 0' }}>
                {selected.condition}
              </p>
              <ConfidenceBar pct={Math.round(selected.confidence * 100)} />

              {selected.alternatives.length > 0 && (
                <div className="flex flex-col gap-0.5 mt-2">
                  {selected.alternatives.map(alt => (
                    <div key={alt.condition} className="flex justify-between">
                      <span style={{ color: '#C0CEC0', fontSize: 12 }}>{alt.condition}</span>
                      <span style={{ color: '#9EAD9E', fontSize: 12 }}>{alt.probability}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Reasoning */}
          <div className="p-3 rounded-xl" style={{ background: '#1C2520' }}>
            <p style={{ color: '#9EAD9E', fontSize: 11, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>
              Analysis Notes
            </p>
            <p style={{ color: '#E0E8E0', fontSize: 13, lineHeight: 1.6 }}>{selected.reasoning}</p>
          </div>

          {/* Follow-up chat actions */}
          {selected.condition.toLowerCase() !== 'unclear' && (
            <div className="flex flex-col gap-2">
              <p style={{ color: '#9EAD9E', fontSize: 11, textTransform: 'uppercase', letterSpacing: 1 }}>
                Follow up in Chat
              </p>
              <div className="grid grid-cols-2 gap-2">
                {[
                  {
                    label: 'Tell me more about this',
                    message: `Looking back at my skin analysis from ${new Date(selected.created_at).toLocaleDateString()}: ${selected.condition} (${Math.round(selected.confidence * 100)}% confidence). The model's reasoning: "${selected.reasoning}" Can you explain what this condition means for my skin?`,
                  },
                  {
                    label: 'Has anything changed?',
                    message: `I have a skin analysis history. My most recent result (${new Date(selected.created_at).toLocaleDateString()}) was ${selected.condition}. Can you help me understand what to look for to track changes in this condition over time?`,
                  },
                  {
                    label: 'Routine for this condition',
                    message: `My skin analysis from ${new Date(selected.created_at).toLocaleDateString()} detected ${selected.condition} (${Math.round(selected.confidence * 100)}% confidence). The model's reasoning: "${selected.reasoning}" Can you build me a skincare routine tailored to this condition?`,
                  },
                  {
                    label: 'Should I see a doctor?',
                    message: `My skin analysis from ${new Date(selected.created_at).toLocaleDateString()} detected ${selected.condition} (${Math.round(selected.confidence * 100)}% confidence). The model's reasoning: "${selected.reasoning}" How serious is this typically, and should I consult a dermatologist?`,
                  },
                ].map(({ label, message }) => (
                  <button
                    key={label}
                    onClick={() => handleChatAbout(message)}
                    className="px-3 py-2 rounded-xl text-xs text-left transition-opacity hover:opacity-80"
                    style={{ background: '#2E3D2F', border: '1px solid #4B5A4C', color: '#E0E8E0', cursor: 'pointer' }}
                  >
                    {label} →
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Full-size zoom overlay */}
      {zoomSrc && (
        <div
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.92)',
            zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center',
            cursor: 'zoom-out',
          }}
          onClick={() => setZoomSrc(null)}
        >
          <img
            src={zoomSrc}
            alt="Full-size skin analysis"
            style={{
              maxWidth: '92vw',
              maxHeight: '92vh',
              borderRadius: 12,
              objectFit: 'contain',
              boxShadow: '0 8px 40px rgba(0,0,0,0.6)',
            }}
          />
          <button
            onClick={() => setZoomSrc(null)}
            style={{
              position: 'absolute', top: 20, right: 24,
              background: 'rgba(255,255,255,0.1)', border: 'none',
              color: '#E0E8E0', fontSize: 22, cursor: 'pointer',
              borderRadius: 8, padding: '4px 10px',
            }}
          >
            ✕
          </button>
        </div>
      )}
    </div>
  )
}

function ConfidenceBar({ pct }: { pct: number }) {
  const color = pct >= 75 ? '#7A9B7D' : pct >= 50 ? '#B5A55A' : '#C07070'
  return (
    <div>
      <div className="flex justify-between mb-1">
        <span style={{ color: '#9EAD9E', fontSize: 11 }}>Confidence</span>
        <span style={{ color, fontSize: 11, fontWeight: 600 }}>{pct}%</span>
      </div>
      <div style={{ background: '#1C2520', borderRadius: 4, height: 6, overflow: 'hidden' }}>
        <div
          style={{
            width: `${pct}%`,
            height: '100%',
            background: color,
            borderRadius: 4,
            transition: 'width 0.5s ease',
          }}
        />
      </div>
    </div>
  )
}

const CARD = { background: '#2E3D2F', border: '1px solid #4B5A4C', borderRadius: 12 } as const
const LABEL_STYLE = { color: '#9EAD9E', fontSize: 10, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase' as const }
const VALUE_STYLE = { color: '#E0E8E0', fontSize: 14, fontWeight: 500 }
const EDIT_BTN = { color: '#9EAD9E', background: 'none', border: 'none', cursor: 'pointer', opacity: 0.5, fontSize: 12, lineHeight: 1, padding: 0 }

function EditableTextCard({ label, value, display, onSave }: {
  label: string
  value: string
  display: string
  onSave: (v: string) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)
  const [saving, setSaving] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  function startEdit() { setDraft(value); setEditing(true); setTimeout(() => inputRef.current?.focus(), 0) }
  function cancel() { setEditing(false) }
  async function commit() {
    if (!draft.trim() || draft.trim() === value) { setEditing(false); return }
    setSaving(true)
    await onSave(draft.trim())
    setSaving(false)
    setEditing(false)
  }

  return (
    <div style={CARD} className="p-3">
      <div className="flex justify-between items-center mb-1">
        <span style={LABEL_STYLE}>{label}</span>
        {!editing && <button onClick={startEdit} style={EDIT_BTN} className="hover:opacity-100 transition-opacity">✏️</button>}
      </div>
      {editing ? (
        <div className="flex gap-1.5 items-center mt-1">
          <input
            ref={inputRef}
            value={draft}
            onChange={e => setDraft(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') cancel() }}
            disabled={saving}
            className="flex-1 px-2 py-1 rounded text-sm outline-none"
            style={{ background: '#1C2520', border: '1px solid #4B5A4C', color: '#E0E8E0' }}
          />
          <button onClick={commit} disabled={saving} style={{ color: '#7A9B7D', background: 'none', border: 'none', cursor: 'pointer', fontSize: 14 }}>✓</button>
          <button onClick={cancel} disabled={saving} style={{ color: '#9EAD9E', background: 'none', border: 'none', cursor: 'pointer', fontSize: 14 }}>✕</button>
        </div>
      ) : (
        <span style={VALUE_STYLE}>{display}</span>
      )}
    </div>
  )
}

function BeardStyleCard({ value, onSave }: {
  value: 'shave' | 'trim' | 'grow' | null
  onSave: (v: string) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value ?? '')
  const [saving, setSaving] = useState(false)

  async function pick(v: string) {
    if (v === value) { setEditing(false); return }
    setSaving(true)
    await onSave(v)
    setSaving(false)
    setEditing(false)
  }

  return (
    <div style={CARD} className="p-3">
      <div className="flex justify-between items-center mb-1">
        <span style={LABEL_STYLE}>Facial Hair</span>
        {!editing && <button onClick={() => { setDraft(value ?? ''); setEditing(true) }} style={EDIT_BTN} className="hover:opacity-100 transition-opacity">✏️</button>}
      </div>
      {editing ? (
        <div className="flex flex-col gap-1 mt-1">
          {(['shave', 'trim', 'grow'] as const).map(opt => (
            <button
              key={opt}
              onClick={() => pick(opt)}
              disabled={saving}
              className="text-left text-xs px-2 py-1.5 rounded-lg transition-colors"
              style={{
                background: draft === opt ? '#3A6B3D' : '#1C2520',
                color: draft === opt ? '#fff' : '#9EAD9E',
                border: `1px solid ${draft === opt ? '#3A6B3D' : '#4B5A4C'}`,
                cursor: 'pointer',
              }}
              onMouseEnter={() => setDraft(opt)}
            >
              {BEARD_LABELS[opt]}
            </button>
          ))}
          <button onClick={() => setEditing(false)} style={{ ...EDIT_BTN, opacity: 1, fontSize: 11, marginTop: 2 }}>Cancel</button>
        </div>
      ) : (
        <span style={VALUE_STYLE}>{BEARD_LABELS[value ?? ''] ?? '—'}</span>
      )}
    </div>
  )
}

function SkinConcernsCard({ concerns, onSave }: {
  concerns: string[]
  onSave: (concerns: string[]) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<string[]>(concerns)
  const [input, setInput] = useState('')
  const [saving, setSaving] = useState(false)

  function startEdit() { setDraft([...concerns]); setEditing(true) }
  function cancel() { setEditing(false); setInput('') }
  function remove(c: string) { setDraft(prev => prev.filter(x => x !== c)) }
  function add() {
    const val = input.trim().toLowerCase()
    if (val && !draft.includes(val)) setDraft(prev => [...prev, val])
    setInput('')
  }
  async function commit() {
    setSaving(true)
    await onSave(draft)
    setSaving(false)
    setEditing(false)
    setInput('')
  }

  return (
    <div style={CARD} className="col-span-2 p-3">
      <div className="flex justify-between items-center mb-1.5">
        <span style={LABEL_STYLE}>Skin Concerns</span>
        {!editing && <button onClick={startEdit} style={EDIT_BTN} className="hover:opacity-100 transition-opacity">✏️</button>}
      </div>
      {editing ? (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap gap-1 min-h-[20px]">
            {draft.map(c => (
              <span key={c} className="flex items-center gap-1 px-2 py-0.5 rounded-full text-xs" style={{ background: '#3A4A3B', color: '#E0E8E0' }}>
                {c}
                <button onClick={() => remove(c)} style={{ color: '#9EAD9E', background: 'none', border: 'none', cursor: 'pointer', lineHeight: 1, padding: 0 }}>×</button>
              </span>
            ))}
            {draft.length === 0 && <span style={{ color: '#9EAD9E', fontSize: 12 }}>No concerns</span>}
          </div>
          <div className="flex gap-1.5">
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); add() } if (e.key === 'Escape') cancel() }}
              placeholder="Add a concern…"
              className="flex-1 px-2 py-1 rounded text-xs outline-none"
              style={{ background: '#1C2520', border: '1px solid #4B5A4C', color: '#E0E8E0' }}
            />
            <button onClick={add} style={{ color: '#7A9B7D', background: 'none', border: 'none', cursor: 'pointer', fontSize: 14 }}>+</button>
          </div>
          <div className="flex gap-2">
            <button onClick={commit} disabled={saving} className="text-xs px-3 py-1 rounded-lg" style={{ background: '#3A6B3D', color: '#fff', border: 'none', cursor: 'pointer' }}>Save</button>
            <button onClick={cancel} disabled={saving} className="text-xs px-3 py-1 rounded-lg" style={{ background: 'none', color: '#9EAD9E', border: '1px solid #4B5A4C', cursor: 'pointer' }}>Cancel</button>
          </div>
        </div>
      ) : (
        concerns.length > 0
          ? <div className="flex flex-wrap gap-1">{concerns.map(c => <Badge key={c} variant="secondary">{c}</Badge>)}</div>
          : <span style={{ color: '#9EAD9E', fontSize: 13 }}>None recorded yet</span>
      )}
    </div>
  )
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div style={CARD} className="p-3">
      <span style={LABEL_STYLE} className="block mb-1">{label}</span>
      <span style={VALUE_STYLE}>{value}</span>
    </div>
  )
}

function PageShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex-1 overflow-y-auto p-6" style={{ background: '#3E4D3F' }}>
      {children}
    </div>
  )
}
