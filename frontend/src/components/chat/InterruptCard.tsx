import { useState } from 'react'

// ── Payload types ─────────────────────────────────────────────────────────────

export interface InterruptOption {
  value: string
  label: string
  subtitle?: string
}

export interface PreviewTags { type: 'tags'; items: string[] }
export interface PreviewKV   { type: 'kv';   pairs: { label: string; value: string }[] }
export interface PreviewText { type: 'text'; content: string; emphasis?: string }
export interface PreviewRoutineStep { ingredient: string; suggested?: string; budget?: string }
export interface PreviewRoutineSteps { type: 'routine_steps'; items: PreviewRoutineStep[] }
export type InterruptPreview = PreviewTags | PreviewKV | PreviewText | PreviewRoutineSteps

export interface InterruptPayload {
  kind: string
  title: string
  options: InterruptOption[]
  preview?: InterruptPreview
}

// ── Preview renderers ─────────────────────────────────────────────────────────

function Preview({ preview }: { preview: InterruptPreview }) {
  if (preview.type === 'routine_steps') {
    return (
      <div className="flex flex-col gap-1.5 mt-2">
        {preview.items.map((item, i) => (
          <div key={i} className="flex flex-col gap-0.5">
            <span className="text-xs font-medium" style={{ color: '#1C2520' }}>
              {i + 1}. {item.ingredient}
            </span>
            {item.suggested && (
              <span className="text-xs pl-3" style={{ color: '#A0742A' }}>
                ⭐ {item.suggested}
              </span>
            )}
            {item.budget && (
              <span className="text-xs pl-3" style={{ color: '#3A6B3D' }}>
                💚 {item.budget}
              </span>
            )}
          </div>
        ))}
      </div>
    )
  }

  if (preview.type === 'tags') {
    return (
      <div className="flex flex-wrap gap-1 mt-2">
        {preview.items.map((item, i) => (
          <span
            key={i}
            className="px-2 py-0.5 rounded-full text-xs"
            style={{ background: '#E8EDE8', color: '#3A6B3D' }}
          >
            {i + 1}. {item}
          </span>
        ))}
      </div>
    )
  }

  if (preview.type === 'kv') {
    return (
      <div className="flex flex-col gap-1 mt-2 text-xs" style={{ color: '#4A5A4B' }}>
        {preview.pairs.map(({ label, value }) => (
          <span key={label}>
            <strong>{label}:</strong> {value || '—'}
          </span>
        ))}
      </div>
    )
  }

  // text
  return (
    <p className="text-xs mt-2 leading-relaxed" style={{ color: '#7A8A7A' }}>
      {preview.emphasis && (
        <strong style={{ color: '#C04A2A' }}>{preview.emphasis} — </strong>
      )}
      {preview.content}
    </p>
  )
}

// ── Component ─────────────────────────────────────────────────────────────────

interface InterruptCardProps {
  payload: InterruptPayload
  onResolve: (choice: string, note: string) => void
  disabled?: boolean
}

export default function InterruptCard({ payload, onResolve, disabled }: InterruptCardProps) {
  const [selected, setSelected] = useState<string | null>(null)
  const [note, setNote] = useState('')

  const canSubmit = selected !== null && !disabled

  function handleSubmit() {
    if (!selected) return
    onResolve(selected, note)
  }

  return (
    <div
      className="rounded-2xl text-sm leading-relaxed w-full"
      style={{
        background: '#fff',
        color: '#1C2520',
        borderBottomLeftRadius: 4,
        boxShadow: '0 1px 4px rgba(0,0,0,.12)',
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <div className="px-4 pt-4 pb-3" style={{ borderBottom: '1px solid #E8EDE8' }}>
        <p className="font-semibold text-sm">{payload.title}</p>
        {payload.preview && <Preview preview={payload.preview} />}
      </div>

      {/* Options */}
      <div className="flex flex-col" style={{ borderBottom: '1px solid #E8EDE8' }}>
        {payload.options.map((opt, i) => {
          const isSelected = selected === opt.value
          return (
            <button
              key={opt.value}
              onClick={() => !disabled && setSelected(opt.value)}
              className="flex items-start gap-3 px-4 py-3 text-left transition-colors"
              style={{
                background: isSelected ? '#F0F5F0' : 'transparent',
                borderBottom: i < payload.options.length - 1 ? '1px solid #E8EDE8' : 'none',
                cursor: disabled ? 'not-allowed' : 'pointer',
                opacity: disabled ? 0.6 : 1,
              }}
            >
              <span
                className="mt-0.5 flex-shrink-0 rounded-full border-2 flex items-center justify-center"
                style={{
                  width: 18,
                  height: 18,
                  borderColor: isSelected ? '#3A6B3D' : '#B0BDB0',
                  background: isSelected ? '#3A6B3D' : 'transparent',
                }}
              >
                {isSelected && (
                  <span className="rounded-full" style={{ width: 6, height: 6, background: '#fff' }} />
                )}
              </span>
              <span className="flex flex-col gap-0.5">
                <span className="font-medium text-sm" style={{ color: '#1C2520' }}>{opt.label}</span>
                {opt.subtitle && (
                  <span className="text-xs" style={{ color: '#7A8A7A' }}>{opt.subtitle}</span>
                )}
              </span>
            </button>
          )
        })}
      </div>

      {/* Free-text input + submit */}
      <div className="px-4 py-3 flex gap-2 items-center">
        <input
          value={note}
          onChange={e => setNote(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && canSubmit && handleSubmit()}
          placeholder="Add a note (optional)…"
          disabled={disabled}
          className="flex-1 px-3 py-2 rounded-lg text-xs outline-none"
          style={{
            background: '#F5F7F5',
            border: '1px solid #D0D8D0',
            color: '#1C2520',
          }}
        />
        <button
          onClick={handleSubmit}
          disabled={!canSubmit}
          className="px-4 py-2 rounded-lg text-xs font-semibold transition-opacity"
          style={{
            background: canSubmit ? '#3A6B3D' : '#B0BDB0',
            color: '#fff',
            cursor: canSubmit ? 'pointer' : 'not-allowed',
          }}
        >
          →
        </button>
      </div>
    </div>
  )
}
