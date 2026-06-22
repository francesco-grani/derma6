import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import {
  apiGetAdminUsers,
  apiGetEvalGolden,
  apiGetEvalStatus,
  apiRunEval,
  type EvalResult,
  type GoldenCase,
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
function EvalTab() {
  const queryClient = useQueryClient()
  const [expanded, setExpanded] = useState<string | null>(null)
  const loggedUpTo = useRef(0)
  const progressEndRef = useRef<HTMLDivElement>(null)

  const { data: golden } = useQuery({
    queryKey: ['admin-eval-golden'],
    queryFn: apiGetEvalGolden,
  })

  const { data: evalStatus } = useQuery({
    queryKey: ['admin-eval-status'],
    queryFn: apiGetEvalStatus,
    refetchInterval: (query) =>
      query.state.data?.status === 'running' ? 2000 : false,
  })

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
  const results = evalStatus?.results
  const progress = evalStatus?.progress ?? []
  const resultMap = new Map<string, EvalResult>(results?.map(r => [r.test_id, r]) ?? [])

  const passed = results?.filter(r => r.passed).length ?? 0
  const total = results?.length ?? 0
  const passRate = total > 0 ? Math.round((passed / total) * 100) : 0

  return (
    <div>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <h2 style={{ color: C.textPrimary, fontSize: 20, fontWeight: 700 }}>Eval Dashboard</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <StatusBadge status={status} startedAt={evalStatus?.started_at} completedAt={evalStatus?.completed_at} />
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

      {/* Live progress feed — visible while running or just after completion */}
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

      {/* Summary cards — only when results available */}
      {results && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 24 }}>
          <StatCard label="Total" value={total} />
          <StatCard label="Passed" value={passed} valueColor={C.pass} />
          <StatCard label="Failed" value={total - passed} valueColor={total - passed > 0 ? C.fail : C.textMuted} />
          <StatCard label="Pass Rate" value={`${passRate}%`} valueColor={passRate >= 80 ? C.pass : passRate >= 60 ? C.amber : C.fail} />
        </div>
      )}

      {/* Golden dataset + results table */}
      <div style={{ marginBottom: 8 }}>
        <p style={{ color: C.textMuted, fontSize: 12, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 8 }}>
          Golden Dataset ({golden?.length ?? 0} cases)
          {results && <span style={{ marginLeft: 8, color: C.textMuted }}>· click a row to see metric detail</span>}
        </p>
      </div>

      <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${C.border}` }}>
        <Table style={{ tableLayout: 'fixed', width: '100%' }}>
          <colgroup>
            <col style={{ width: 88 }} />   {/* ID */}
            <col style={{ width: 148 }} />  {/* Tool */}
            <col />                         {/* Input — takes remaining space */}
            <col style={{ width: 200 }} />  {/* Expected */}
            {results && <col style={{ width: 110 }} />}  {/* Metrics */}
            {results && <col style={{ width: 68 }} />}   {/* Status */}
          </colgroup>
          <TableHeader>
            <TableRow style={{ background: C.bgDark, borderColor: C.border }}>
              <TableHead style={{ color: C.textMuted, fontSize: 11, letterSpacing: '0.06em' }}>ID</TableHead>
              <TableHead style={{ color: C.textMuted, fontSize: 11, letterSpacing: '0.06em' }}>Tool</TableHead>
              <TableHead style={{ color: C.textMuted, fontSize: 11, letterSpacing: '0.06em' }}>Input</TableHead>
              <TableHead style={{ color: C.textMuted, fontSize: 11, letterSpacing: '0.06em' }}>Expected</TableHead>
              {results && <TableHead style={{ color: C.textMuted, fontSize: 11, letterSpacing: '0.06em' }}>Metrics</TableHead>}
              {results && <TableHead style={{ color: C.textMuted, fontSize: 11, letterSpacing: '0.06em' }}>Status</TableHead>}
            </TableRow>
          </TableHeader>
          <TableBody>
            {(golden ?? []).map((g: GoldenCase) => {
              const result = resultMap.get(g.id)
              const isExpanded = expanded === g.id
              return (
                <>
                  <TableRow
                    key={g.id}
                    onClick={() => result && setExpanded(isExpanded ? null : g.id)}
                    style={{
                      borderColor: C.border,
                      background: isExpanded ? C.bgDark : C.bg,
                      cursor: result ? 'pointer' : 'default',
                    }}
                  >
                    <TableCell style={{ color: C.textMuted, fontSize: 12, fontFamily: 'monospace', overflow: 'hidden', whiteSpace: 'nowrap' }}>{g.id}</TableCell>
                    <TableCell style={{ color: C.textPrimary, fontSize: 12, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>{g.tool}</TableCell>
                    <TableCell style={{ color: C.textMuted, fontSize: 12, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }} title={g.input}>
                      {g.input}
                    </TableCell>
                    <TableCell style={{ color: C.textMuted, fontSize: 12, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }} title={g.expected_output ?? ''}>
                      {g.expected_output ?? '—'}
                    </TableCell>
                    {results && (
                      <TableCell style={{ overflow: 'hidden' }}>
                        {result ? (
                          <div style={{ display: 'flex', gap: 3 }}>
                            {result.metrics.map(m => (
                              <span
                                key={m.name}
                                title={`${m.name}: ${m.score} / ${m.threshold}`}
                                style={{
                                  fontSize: 11,
                                  padding: '2px 5px',
                                  borderRadius: 4,
                                  background: m.passed ? '#1A3A2A' : '#3A1A1A',
                                  color: m.passed ? C.pass : C.fail,
                                  border: `1px solid ${m.passed ? '#2A5A3A' : '#5A2A2A'}`,
                                  cursor: 'help',
                                  fontFamily: 'monospace',
                                  flexShrink: 0,
                                }}
                              >
                                {m.score.toFixed(2)}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span style={{ color: C.textMuted, fontSize: 12 }}>—</span>
                        )}
                      </TableCell>
                    )}
                    {results && (
                      <TableCell>
                        {result ? (
                          <Badge
                            style={{
                              background: result.passed ? '#1A3A2A' : '#3A1A1A',
                              color: result.passed ? C.pass : C.fail,
                              border: `1px solid ${result.passed ? '#2A5A3A' : '#5A2A2A'}`,
                              fontSize: 11,
                              fontWeight: 600,
                            }}
                          >
                            {result.passed ? 'PASS' : 'FAIL'}
                          </Badge>
                        ) : (
                          <span style={{ color: C.textMuted, fontSize: 12 }}>—</span>
                        )}
                      </TableCell>
                    )}
                  </TableRow>

                  {/* Expanded metric detail row */}
                  {isExpanded && result && (
                    <TableRow key={`${g.id}-detail`} style={{ background: C.bgDark, borderColor: C.border }}>
                      <TableCell colSpan={6} style={{ padding: '12px 16px' }}>
                        <MetricDetail result={result} />
                      </TableCell>
                    </TableRow>
                  )}
                </>
              )
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

// ── Metric detail panel (expanded row) ───────────────────────────────────────
function MetricDetail({ result }: { result: EvalResult }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {result.metrics.map(m => (
        <div key={m.name} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ color: C.textPrimary, fontSize: 12, fontWeight: 600, minWidth: 220 }}>{m.name}</span>
            <div style={{ flex: 1, maxWidth: 160 }}>
              <Progress
                value={m.score * 100}
                style={{
                  height: 6,
                  background: '#2E3D2F',
                }}
                className="[&>div]:transition-all"
              />
            </div>
            <span style={{ color: m.passed ? C.pass : C.fail, fontSize: 12, fontFamily: 'monospace', minWidth: 50 }}>
              {m.score.toFixed(3)}
            </span>
            <span style={{ color: C.textMuted, fontSize: 11 }}>/ {m.threshold}</span>
            <Badge
              style={{
                background: m.passed ? '#1A3A2A' : '#3A1A1A',
                color: m.passed ? C.pass : C.fail,
                border: `1px solid ${m.passed ? '#2A5A3A' : '#5A2A2A'}`,
                fontSize: 10,
              }}
            >
              {m.passed ? 'PASS' : 'FAIL'}
            </Badge>
            <span style={{ color: C.textMuted, fontSize: 11 }}>{m.duration_s}s</span>
          </div>
          {m.reason && (
            <p style={{ color: C.textMuted, fontSize: 11, margin: 0, paddingLeft: 230, lineHeight: 1.5 }}>
              {m.reason}
            </p>
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
  const { username } = useAuth()
  const [activeTab, setActiveTab] = useState<Tab>('users')

  if (username !== 'admin') {
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
