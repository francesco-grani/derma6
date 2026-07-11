import { Fragment, useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import {
  apiGetAdminUsers,
  apiGetEvalStatus,
  apiRunEval,
  apiExportEvalHtml,
  type EvalResult,
} from '@/lib/api'
import { useAuth } from '@/lib/auth'

// ── Colour constants ──────────────────────────────────────────────────────────
const C = {
  bg: '#3E4D3F',
  bgDark: '#2E3D2F',
  bgCard: '#354535',
  border: '#4B5A4C',
  textPrimary: '#E0E8E0',
  textMuted: '#9EAD9E',
  textError: '#F0B8B8',
  btnPrimary: '#7A9B7D',
  btnPrimaryText: '#1C2520',
  pass: '#6EBF8B',
  fail: '#E57373',
  amber: '#C4933F',
}

// ── Tab bar ───────────────────────────────────────────────────────────────────
type Tab = 'users' | 'eval'

function TabBar({ active, onChange }: { active: Tab; onChange: (t: Tab) => void }) {
  const tabs: { id: Tab; label: string }[] = [
    { id: 'users', label: 'Users & Cost' },
    { id: 'eval', label: 'Eval Dashboard' },
  ]
  return (
    <div style={{ display: 'flex', gap: 4, marginBottom: 24 }}>
      {tabs.map(t => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          style={{
            padding: '6px 18px',
            borderRadius: 8,
            border: `1px solid ${active === t.id ? C.btnPrimary : C.border}`,
            background: active === t.id ? C.btnPrimary : 'transparent',
            color: active === t.id ? C.btnPrimaryText : C.textMuted,
            fontWeight: active === t.id ? 600 : 400,
            fontSize: 13,
            cursor: 'pointer',
            transition: 'all 0.15s',
          }}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

// ── Users tab ─────────────────────────────────────────────────────────────────
function UsersTab() {
  const { data: users, isLoading, error } = useQuery({
    queryKey: ['admin-users'],
    queryFn: apiGetAdminUsers,
  })

  if (isLoading) return <p style={{ color: C.textMuted }}>Loading users…</p>
  if (error) return <p style={{ color: C.textError }}>Failed to load users.</p>

  const totalCost = users?.reduce((s, u) => s + u.total_cost_usd, 0) ?? 0
  const totalPrompt = users?.reduce((s, u) => s + u.total_prompt_tokens, 0) ?? 0
  const totalCompletion = users?.reduce((s, u) => s + u.total_completion_tokens, 0) ?? 0

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 20 }}>
        <h2 style={{ color: C.textPrimary, fontSize: 20, fontWeight: 700 }}>
          Users ({users?.length ?? 0})
        </h2>
        <span style={{ color: C.textMuted, fontSize: 13 }}>
          {(totalPrompt + totalCompletion).toLocaleString()} total tokens · ${totalCost.toFixed(4)} total cost
        </span>
      </div>

      <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${C.border}` }}>
        <Table>
          <TableHeader>
            <TableRow style={{ background: C.bgDark, borderColor: C.border }}>
              {['ID', 'Username', 'Skin Type', 'Concerns', 'Shaving', 'Medical Flags', 'Onboarding', 'Prompt Tokens', 'Completion Tokens', 'Cost (USD)'].map(h => (
                <TableHead key={h} style={{ color: C.textMuted, fontSize: 11, letterSpacing: '0.06em' }}>{h}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {users?.map(u => (
              <TableRow key={u.id} style={{ borderColor: C.border, background: C.bg }}>
                <TableCell style={{ color: C.textMuted, fontSize: 13 }}>{u.id}</TableCell>
                <TableCell style={{ color: C.textPrimary, fontSize: 13, fontWeight: 500 }}>{u.username}</TableCell>
                <TableCell style={{ color: C.textMuted, fontSize: 13 }}>{u.skin_type ?? '—'}</TableCell>
                <TableCell style={{ color: C.textMuted, fontSize: 13 }}>{u.skin_concerns ?? '—'}</TableCell>
                <TableCell style={{ color: C.textMuted, fontSize: 13 }}>{u.has_shaving_routine === null ? '—' : u.has_shaving_routine ? 'Yes' : 'No'}</TableCell>
                <TableCell style={{ color: C.textMuted, fontSize: 13 }}>{u.medical_flags ?? '—'}</TableCell>
                <TableCell style={{ fontSize: 13 }}>{u.onboarding_complete ? '✅' : '⏳'}</TableCell>
                <TableCell style={{ color: C.textMuted, fontSize: 13 }}>{u.total_prompt_tokens.toLocaleString()}</TableCell>
                <TableCell style={{ color: C.textMuted, fontSize: 13 }}>{u.total_completion_tokens.toLocaleString()}</TableCell>
                <TableCell style={{ color: u.total_cost_usd > 0 ? C.amber : C.textMuted, fontSize: 13, fontWeight: u.total_cost_usd > 0 ? 600 : 400 }}>
                  ${u.total_cost_usd.toFixed(6)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

// ── Eval tab ──────────────────────────────────────────────────────────────────
const LS_KEY = 'derma6_eval_results'

const CATEGORIES = [
  'SPF Recommender',
  'Conflict Checker',
  'Routine Sequencer',
  'Skin Type Advisor',
  'Introduction Scheduler',
  'KB — Answer Quality',
  'KB — RAG Pipeline',
] as const

const KIND_LABEL: Record<string, string> = {
  'llm-judge':   'LLM',
  'programmatic': 'py',
  'rag':         'RAG',
}
const KIND_COLOR: Record<string, string> = {
  'llm-judge':   '#4A5A8A',
  'programmatic': '#5A7A5A',
  'rag':         '#7A5A2A',
}

interface CachedEval {
  results: EvalResult[]
  completed_at: string
}

function loadCachedEval(): CachedEval | null {
  try {
    const raw = localStorage.getItem(LS_KEY)
    return raw ? (JSON.parse(raw) as CachedEval) : null
  } catch {
    return null
  }
}

function saveCachedEval(results: EvalResult[], completed_at: string) {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify({ results, completed_at }))
  } catch {
    // localStorage quota exceeded — silently ignore
  }
}

// ── Category section ──────────────────────────────────────────────────────────
function CategorySection({
  category,
  rows,
  expanded,
  onExpand,
}: {
  category: string
  rows: EvalResult[]
  expanded: string | null
  onExpand: (key: string | null) => void
}) {
  const catPassed = rows.filter(r => r.passed).length
  const allPass = catPassed === rows.length
  const anyFail = catPassed < rows.length

  return (
    <div style={{ marginBottom: 20 }}>
      {/* Section header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6,
        paddingBottom: 6, borderBottom: `1px solid ${C.border}`,
      }}>
        <span style={{ color: C.textPrimary, fontSize: 13, fontWeight: 600 }}>{category}</span>
        <span style={{
          fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 10,
          background: allPass ? '#1A3A2A' : anyFail ? '#3A1A1A' : C.bgDark,
          color: allPass ? C.pass : anyFail ? C.fail : C.textMuted,
          border: `1px solid ${allPass ? '#2A5A3A' : anyFail ? '#5A2A2A' : C.border}`,
        }}>
          {catPassed}/{rows.length}
        </span>
      </div>

      <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${C.border}` }}>
        <Table style={{ tableLayout: 'fixed', width: '100%' }}>
          <colgroup>
            <col style={{ width: 96 }} />
            <col />
            <col style={{ width: 230 }} />
            <col style={{ width: 130 }} />
            <col style={{ width: 68 }} />
          </colgroup>
          <TableHeader>
            <TableRow style={{ background: C.bgDark, borderColor: C.border }}>
              <TableHead style={{ color: C.textMuted, fontSize: 11, letterSpacing: '0.06em' }}>Test ID</TableHead>
              <TableHead style={{ color: C.textMuted, fontSize: 11, letterSpacing: '0.06em' }}>Input</TableHead>
              <TableHead style={{ color: C.textMuted, fontSize: 11, letterSpacing: '0.06em' }}>Expected</TableHead>
              <TableHead style={{ color: C.textMuted, fontSize: 11, letterSpacing: '0.06em' }}>Metrics</TableHead>
              <TableHead style={{ color: C.textMuted, fontSize: 11, letterSpacing: '0.06em' }}>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map(r => {
              const key = `${r.test_name}`
              const isExpanded = expanded === key
              return (
                <Fragment key={key}>
                  <TableRow
                    onClick={() => onExpand(isExpanded ? null : key)}
                    style={{
                      borderColor: C.border,
                      background: isExpanded ? C.bgDark : C.bg,
                      cursor: 'pointer',
                    }}
                  >
                    <TableCell style={{ verticalAlign: 'top', padding: '8px 12px' }}>
                      <div style={{ color: C.textMuted, fontSize: 12, fontFamily: 'monospace', overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>{r.test_id}</div>
                    </TableCell>
                    <TableCell style={{ verticalAlign: 'top', padding: '8px 12px' }}>
                      <div style={{ color: C.textMuted, fontSize: 12, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }} title={r.input}>{r.input}</div>
                    </TableCell>
                    <TableCell style={{ verticalAlign: 'top', padding: '8px 12px' }}>
                      <div style={{ color: C.textMuted, fontSize: 12, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }} title={r.expected_output ?? ''}>{r.expected_output ?? '—'}</div>
                    </TableCell>
                    <TableCell style={{ overflow: 'hidden', padding: '8px 12px' }}>
                      <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
                        {r.metrics.map(m => (
                          <span
                            key={m.name}
                            title={`${m.name}: ${m.score.toFixed(3)} / ${m.threshold}`}
                            style={{
                              fontSize: 10,
                              padding: '2px 5px',
                              borderRadius: 4,
                              background: m.passed ? '#1A3A2A' : '#3A1A1A',
                              color: m.passed ? C.pass : C.fail,
                              border: `1px solid ${KIND_COLOR[m.kind] ?? C.border}`,
                              cursor: 'help',
                              fontFamily: 'monospace',
                              flexShrink: 0,
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: 3,
                            }}
                          >
                            <span style={{ color: KIND_COLOR[m.kind] ?? C.textMuted, opacity: 0.9 }}>
                              {KIND_LABEL[m.kind] ?? '?'}
                            </span>
                            {m.score.toFixed(2)}
                          </span>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell style={{ padding: '8px 12px' }}>
                      <Badge
                        style={{
                          background: r.passed ? '#1A3A2A' : '#3A1A1A',
                          color: r.passed ? C.pass : C.fail,
                          border: `1px solid ${r.passed ? '#2A5A3A' : '#5A2A2A'}`,
                          fontSize: 11,
                          fontWeight: 600,
                        }}
                      >
                        {r.passed ? 'PASS' : 'FAIL'}
                      </Badge>
                    </TableCell>
                  </TableRow>

                  {isExpanded && (
                    <TableRow style={{ background: C.bgDark, borderColor: C.border }}>
                      <TableCell colSpan={5} style={{ padding: '12px 16px', overflow: 'hidden' }}>
                        <MetricDetail result={r} />
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              )
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

function EvalTab() {
  const queryClient = useQueryClient()
  const [expanded, setExpanded] = useState<string | null>(null)
  const [activeCategory, setActiveCategory] = useState<string>('All')
  const [cachedEval, setCachedEval] = useState<CachedEval | null>(() => loadCachedEval())
  const loggedUpTo = useRef(0)
  const progressEndRef = useRef<HTMLDivElement>(null)

  const { data: evalStatus } = useQuery({
    queryKey: ['admin-eval-status'],
    queryFn: apiGetEvalStatus,
    refetchInterval: (query) =>
      query.state.data?.status === 'running' ? 2000 : false,
  })

  // Persist results to localStorage whenever a run completes
  useEffect(() => {
    if (evalStatus?.status === 'completed' && evalStatus.results) {
      const ts = evalStatus.completed_at ?? new Date().toISOString()
      saveCachedEval(evalStatus.results, ts)
      setCachedEval({ results: evalStatus.results, completed_at: ts })
    }
  }, [evalStatus?.status, evalStatus?.results, evalStatus?.completed_at])

  // Log new progress lines to the browser console as they arrive
  useEffect(() => {
    const lines = evalStatus?.progress ?? []
    for (let i = loggedUpTo.current; i < lines.length; i++) {
      // eslint-disable-next-line no-console
      console.log(`[eval] ${lines[i]}`)
    }
    loggedUpTo.current = lines.length
    if (lines.length > 0) progressEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [evalStatus?.progress])

  // Reset log cursor when a new run starts
  useEffect(() => {
    if (evalStatus?.status === 'running' && (evalStatus.progress ?? []).length === 0) {
      loggedUpTo.current = 0
    }
  }, [evalStatus?.status])

  const runMutation = useMutation({
    mutationFn: apiRunEval,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin-eval-status'] }),
  })

  const status = evalStatus?.status ?? 'idle'
  const results = evalStatus?.results ?? (status === 'idle' ? cachedEval?.results ?? null : null)
  const completedAt = evalStatus?.completed_at ?? cachedEval?.completed_at ?? null

  function triggerDownload(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }

  function handleExportJson() {
    if (!results) return
    const payload = JSON.stringify({ completed_at: completedAt, results }, null, 2)
    triggerDownload(new Blob([payload], { type: 'application/json' }), `eval_results_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.json`)
  }

  async function handleExportHtml() {
    if (!results) return
    const blob = await apiExportEvalHtml(results, completedAt)
    triggerDownload(blob, `eval_results_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.html`)
  }
  const isCached = !evalStatus?.results && status === 'idle' && !!cachedEval
  const progress = evalStatus?.progress ?? []

  const passed = results?.filter(r => r.passed).length ?? 0
  const total = results?.length ?? 0
  const passRate = total > 0 ? Math.round((passed / total) * 100) : 0

  // Group results by category
  const byCategory = CATEGORIES.reduce<Record<string, EvalResult[]>>((acc, cat) => {
    acc[cat] = results?.filter(r => r.category === cat) ?? []
    return acc
  }, {})

  const visibleCategories = activeCategory === 'All'
    ? CATEGORIES.filter(c => (byCategory[c]?.length ?? 0) > 0)
    : CATEGORIES.filter(c => c === activeCategory)

  return (
    <div>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <h2 style={{ color: C.textPrimary, fontSize: 20, fontWeight: 700 }}>Eval Dashboard</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <StatusBadge status={status} startedAt={evalStatus?.started_at ?? null} completedAt={evalStatus?.completed_at ?? null} />
          {isCached && cachedEval && (
            <span style={{ fontSize: 11, color: C.textMuted }}>
              cached · {new Date(cachedEval.completed_at).toLocaleString()}
            </span>
          )}
          {results && (
            <>
              <Button
                onClick={handleExportJson}
                style={{ background: C.bgCard, color: C.textPrimary, fontWeight: 600, fontSize: 13, border: `1px solid ${C.border}` }}
              >
                Export JSON
              </Button>
              <Button
                onClick={handleExportHtml}
                style={{ background: C.bgCard, color: C.textPrimary, fontWeight: 600, fontSize: 13, border: `1px solid ${C.border}` }}
              >
                Export HTML
              </Button>
            </>
          )}
          <Button
            onClick={() => runMutation.mutate()}
            disabled={status === 'running' || runMutation.isPending}
            style={{
              background: status === 'running' ? C.bgCard : C.btnPrimary,
              color: status === 'running' ? C.textMuted : C.btnPrimaryText,
              fontWeight: 600,
              fontSize: 13,
              cursor: status === 'running' ? 'not-allowed' : 'pointer',
              border: 'none',
            }}
          >
            {status === 'running' ? 'Running…' : status === 'completed' ? 'Re-run Eval' : 'Run Eval Suite'}
          </Button>
        </div>
      </div>

      {/* Error banner */}
      {status === 'error' && evalStatus?.error && (
        <div style={{ background: '#3D2020', border: `1px solid #7A3030`, borderRadius: 8, padding: '10px 14px', marginBottom: 16 }}>
          <p style={{ color: C.textError, fontSize: 13, margin: 0 }}>{evalStatus.error}</p>
        </div>
      )}

      {/* Live progress feed */}
      {progress.length > 0 && (
        <div style={{ background: '#1C2520', border: `1px solid ${C.border}`, borderRadius: 8, padding: '10px 14px', marginBottom: 20, maxHeight: 160, overflowY: 'auto', fontFamily: 'monospace' }}>
          {progress.map((line, i) => {
            const isPass = line.includes('→ PASS')
            const isFail = line.includes('→ FAIL')
            return (
              <p key={i} style={{ margin: '1px 0', fontSize: 11, color: isPass ? C.pass : isFail ? C.fail : C.textMuted }}>
                {line}
              </p>
            )
          })}
          <div ref={progressEndRef} />
        </div>
      )}

      {/* Summary cards */}
      {results && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 }}>
          <StatCard label="Total" value={total} />
          <StatCard label="Passed" value={passed} valueColor={C.pass} />
          <StatCard label="Failed" value={total - passed} valueColor={total - passed > 0 ? C.fail : C.textMuted} />
          <StatCard label="Pass Rate" value={`${passRate}%`} valueColor={passRate >= 80 ? C.pass : passRate >= 60 ? C.amber : C.fail} />
        </div>
      )}

      {/* Metric kind legend */}
      {results && (
        <div style={{ display: 'flex', gap: 10, marginBottom: 16, alignItems: 'center' }}>
          <span style={{ color: C.textMuted, fontSize: 11 }}>Metric type:</span>
          {Object.entries(KIND_LABEL).map(([kind, label]) => (
            <span key={kind} style={{ fontSize: 11, padding: '2px 7px', borderRadius: 4, background: KIND_COLOR[kind], color: '#E0E8E0', fontFamily: 'monospace' }}>
              {label}
            </span>
          ))}
          <span style={{ color: C.textMuted, fontSize: 11, marginLeft: 4 }}>— hover a score chip for details</span>
        </div>
      )}

      {/* Category filter pills */}
      {results && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 20 }}>
          {['All', ...CATEGORIES].map(cat => {
            const isActive = activeCategory === cat
            const catRows = cat === 'All' ? results : (byCategory[cat] ?? [])
            const catPassed = catRows.filter(r => r.passed).length
            const allPass = catPassed === catRows.length && catRows.length > 0
            const anyFail = catPassed < catRows.length && catRows.length > 0
            return (
              <button
                key={cat}
                onClick={() => { setActiveCategory(cat); setExpanded(null) }}
                style={{
                  padding: '4px 12px',
                  borderRadius: 20,
                  fontSize: 12,
                  fontWeight: isActive ? 600 : 400,
                  border: `1px solid ${isActive ? C.btnPrimary : C.border}`,
                  background: isActive ? C.btnPrimary : 'transparent',
                  color: isActive ? C.btnPrimaryText : allPass ? C.pass : anyFail ? C.fail : C.textMuted,
                  cursor: 'pointer',
                  transition: 'all 0.12s',
                }}
              >
                {cat}
                {catRows.length > 0 && (
                  <span style={{ marginLeft: 5, opacity: 0.7 }}>
                    {catPassed}/{catRows.length}
                  </span>
                )}
              </button>
            )
          })}
        </div>
      )}

      {/* No results yet */}
      {!results && (
        <div style={{ color: C.textMuted, fontSize: 13, padding: '32px 0', textAlign: 'center' }}>
          No eval results yet — click <strong style={{ color: C.textPrimary }}>Run Eval Suite</strong> to start.
        </div>
      )}

      {/* Category sections */}
      {results && visibleCategories.map(cat => (
        <CategorySection
          key={cat}
          category={cat}
          rows={byCategory[cat] ?? []}
          expanded={expanded}
          onExpand={setExpanded}
        />
      ))}
    </div>
  )
}

// ── Metric detail panel (expanded row) ───────────────────────────────────────
function MetricDetail({ result }: { result: EvalResult }) {
  return (
    <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 10 }}>
      {result.metrics.map(m => (
        <div key={m.name} style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ color: C.textPrimary, fontSize: 12, fontWeight: 600, minWidth: 220, flexShrink: 0 }}>{m.name}</span>
            <div style={{ width: 160, flexShrink: 0 }}>
              <Progress
                value={m.score * 100}
                style={{ height: 6, background: '#2E3D2F' }}
                className="[&>div]:transition-all"
              />
            </div>
            <span style={{ color: m.passed ? C.pass : C.fail, fontSize: 12, fontFamily: 'monospace', minWidth: 50, flexShrink: 0 }}>
              {m.score.toFixed(3)}
            </span>
            <span style={{ color: C.textMuted, fontSize: 11, flexShrink: 0 }}>/ {m.threshold}</span>
            <Badge
              style={{
                background: m.passed ? '#1A3A2A' : '#3A1A1A',
                color: m.passed ? C.pass : C.fail,
                border: `1px solid ${m.passed ? '#2A5A3A' : '#5A2A2A'}`,
                fontSize: 10,
                flexShrink: 0,
              }}
            >
              {m.passed ? 'PASS' : 'FAIL'}
            </Badge>
            <span style={{ color: C.textMuted, fontSize: 11, flexShrink: 0 }}>{m.duration_s}s</span>
          </div>
          {m.reason && (
            <div style={{ display: 'grid', gridTemplateColumns: '230px 1fr', columnGap: 10 }}>
              <div />
              <p style={{ color: C.textMuted, fontSize: 11, margin: 0, lineHeight: 1.5, wordBreak: 'break-word', overflowWrap: 'break-word' }}>
                {m.reason}
              </p>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

// ── Small helpers ─────────────────────────────────────────────────────────────
function StatCard({ label, value, valueColor }: { label: string; value: string | number; valueColor?: string }) {
  return (
    <div
      style={{
        background: C.bgDark,
        border: `1px solid ${C.border}`,
        borderRadius: 10,
        padding: '14px 18px',
      }}
    >
      <p style={{ color: C.textMuted, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em', margin: 0 }}>{label}</p>
      <p style={{ color: valueColor ?? C.textPrimary, fontSize: 28, fontWeight: 700, margin: '4px 0 0' }}>{value}</p>
    </div>
  )
}

function StatusBadge({
  status,
  startedAt,
  completedAt,
}: {
  status: string
  startedAt: string | null
  completedAt: string | null
}) {
  const colors: Record<string, { bg: string; fg: string }> = {
    idle:      { bg: '#2A3A2A', fg: C.textMuted },
    running:   { bg: '#2A2A3A', fg: '#8888EE' },
    completed: { bg: '#1A3A2A', fg: C.pass },
    error:     { bg: '#3A1A1A', fg: C.fail },
  }
  const c = colors[status] ?? colors.idle
  const ts = completedAt ?? startedAt
  const tsLabel = ts ? new Date(ts).toLocaleTimeString() : null

  return (
    <span
      style={{
        fontSize: 12,
        padding: '4px 10px',
        borderRadius: 6,
        background: c.bg,
        color: c.fg,
        fontWeight: 600,
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
      }}
    >
      {status === 'running' && <span style={{ display: 'inline-block', animation: 'spin 1s linear infinite' }}>⟳</span>}
      {status.toUpperCase()}
      {tsLabel && <span style={{ fontWeight: 400, opacity: 0.75 }}>{tsLabel}</span>}
    </span>
  )
}

// ── Page root ─────────────────────────────────────────────────────────────────
export default function AdminPage() {
  const { isAdmin } = useAuth()
  const [activeTab, setActiveTab] = useState<Tab>('users')

  if (!isAdmin) {
    return (
      <div className="flex-1 p-6" style={{ background: C.bg }}>
        <p style={{ color: C.textError }}>Access denied.</p>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto p-6" style={{ background: C.bg }}>
      <TabBar active={activeTab} onChange={setActiveTab} />
      {activeTab === 'users' ? <UsersTab /> : <EvalTab />}
    </div>
  )
}
