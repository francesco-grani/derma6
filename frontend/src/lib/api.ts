/** Typed fetch wrappers. All authenticated calls inject the JWT from localStorage. */

export function getToken(): string | null {
  return localStorage.getItem('derma6_token')
}

export function getUsername(): string | null {
  return localStorage.getItem('derma6_username')
}

export function getIsAdmin(): boolean {
  return localStorage.getItem('derma6_is_admin') === 'true'
}

export function setAuth(token: string, username: string, isAdmin: boolean) {
  localStorage.setItem('derma6_token', token)
  localStorage.setItem('derma6_username', username)
  localStorage.setItem('derma6_is_admin', String(isAdmin))
}

export function clearAuth() {
  localStorage.removeItem('derma6_token')
  localStorage.removeItem('derma6_username')
  localStorage.removeItem('derma6_is_admin')
}

function handleUnauthorized() {
  clearAuth()
  window.location.replace('/login')
}

async function authedFetch(path: string, init: RequestInit = {}) {
  const token = getToken()
  const res = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers ?? {}),
    },
  })
  if (res.status === 401) {
    handleUnauthorized()
    throw new Error('Session expired')
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? 'Request failed')
  }
  return res
}

// ── Auth ──────────────────────────────────────────────────────────────────

export async function apiRegister(username: string, password: string) {
  const res = await fetch('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? 'Registration failed')
  }
  return res.json() as Promise<{ access_token: string; username: string; is_admin: boolean }>
}

export async function apiLogin(username: string, password: string) {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? 'Login failed')
  }
  return res.json() as Promise<{ access_token: string; username: string; is_admin: boolean }>
}

// ── Profile ───────────────────────────────────────────────────────────────

export interface UserProfile {
  username: string
  skin_type: string | null
  skin_concerns: string[]
  has_shaving_routine: boolean | null
  beard_style: 'shave' | 'trim' | 'grow' | null
  location: string | null
  medical_flags: string[]
  onboarding_complete: boolean
}

export async function apiGetProfile(): Promise<UserProfile> {
  const res = await authedFetch('/api/me/profile')
  return res.json()
}

export type ProfilePatch = Partial<Pick<UserProfile, 'skin_type' | 'beard_style' | 'location' | 'skin_concerns'>>

export async function apiPatchProfile(patch: ProfilePatch): Promise<UserProfile> {
  const res = await authedFetch('/api/me/profile', {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
  return res.json()
}

// ── Routines ──────────────────────────────────────────────────────────────

export interface RoutineStep {
  position: number
  ingredient: string
  product_name: string | null
  budget_product: string | null
}

export interface Routine {
  name: string
  steps: RoutineStep[]
}

export async function apiGetRoutines(): Promise<Routine[]> {
  const res = await authedFetch('/api/me/routines')
  return res.json()
}

export async function apiDeleteRoutine(name: string): Promise<void> {
  await authedFetch(`/api/me/routines/${encodeURIComponent(name)}`, { method: 'DELETE' })
}

export async function apiRenameRoutine(oldName: string, newName: string): Promise<void> {
  await authedFetch(`/api/me/routines/${encodeURIComponent(oldName)}`, {
    method: 'PATCH',
    body: JSON.stringify({ new_name: newName }),
  })
}

// ── Export ────────────────────────────────────────────────────────────────

export function exportUrl(format: 'html' | 'pdf') {
  return `/api/me/export?format=${format}`
}

// ── Sessions ──────────────────────────────────────────────────────────────

export interface ChatSessionInfo {
  session_id: string
  title: string | null
  created_at: string
  updated_at: string
}

export async function apiGetSessions(): Promise<ChatSessionInfo[]> {
  const res = await authedFetch('/api/me/sessions')
  return res.json()
}

export async function apiCreateSession(): Promise<ChatSessionInfo> {
  const res = await authedFetch('/api/me/sessions', { method: 'POST' })
  return res.json()
}

export async function apiDeleteSession(session_id: string): Promise<void> {
  await authedFetch(`/api/me/sessions/${encodeURIComponent(session_id)}`, { method: 'DELETE' })
}

// ── Skin Analysis ─────────────────────────────────────────────────────────

export interface Alternative {
  condition: string
  probability: string
}

export interface SkinAnalysisResult {
  condition: string
  confidence: number
  alternatives: Alternative[]
  reasoning: string
  disclaimer: string
}

export interface SkinAnalysisRecord {
  id: number
  condition: string
  confidence: number
  alternatives: Alternative[]
  reasoning: string
  disclaimer: string
  image_b64: string | null
  thumbnail_b64: string | null
  created_at: string
}

export async function apiGetSkinAnalyses(): Promise<SkinAnalysisRecord[]> {
  const res = await authedFetch('/api/me/skin-analyses')
  return res.json()
}

export async function apiDeleteSkinAnalysis(id: number): Promise<void> {
  await authedFetch(`/api/me/skin-analyses/${id}`, { method: 'DELETE' })
}

export async function apiAnalyzeSkin(file: File): Promise<SkinAnalysisResult> {
  const token = getToken()
  const body = new FormData()
  body.append('file', file)
  const res = await fetch('/api/me/analyze-skin', {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body,
  })
  if (res.status === 401) {
    handleUnauthorized()
    throw new Error('Session expired')
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? 'Analysis failed')
  }
  return res.json()
}

export async function apiSaveMedicalFlag(condition: string): Promise<void> {
  await authedFetch('/api/me/medical-flags', {
    method: 'POST',
    body: JSON.stringify({ condition }),
  })
}

// ── Admin ─────────────────────────────────────────────────────────────────

export interface AdminUser {
  id: number
  username: string
  skin_type: string | null
  skin_concerns: string | null
  has_shaving_routine: boolean | null
  medical_flags: string | null
  onboarding_complete: boolean
  total_prompt_tokens: number
  total_completion_tokens: number
  total_cost_usd: number
}

export async function apiGetAdminUsers(): Promise<AdminUser[]> {
  const res = await authedFetch('/api/admin/users')
  return res.json()
}

// ── Eval dashboard ────────────────────────────────────────────────────────────

export interface GoldenCase {
  id: string
  tool: string
  input: string
  actual_output: string
  expected_output: string | null
  retrieval_context: string[]
  tags: string[]
}

export interface MetricResult {
  name: string
  score: number
  threshold: number
  passed: boolean
  reason: string | null
  duration_s: number
  kind: 'llm-judge' | 'programmatic' | 'rag'
}

export interface EvalResult {
  test_id: string
  test_name: string
  category: string
  tool: string
  input: string
  expected_output: string | null
  passed: boolean
  metrics: MetricResult[]
}

export interface EvalStatus {
  status: 'idle' | 'running' | 'completed' | 'error'
  started_at: string | null
  completed_at: string | null
  results: EvalResult[] | null
  error: string | null
  progress: string[]
}

export async function apiGetEvalGolden(): Promise<GoldenCase[]> {
  const res = await authedFetch('/api/admin/eval/golden')
  return res.json()
}

export async function apiGetEvalStatus(): Promise<EvalStatus> {
  const res = await authedFetch('/api/admin/eval/status')
  return res.json()
}

export async function apiRunEval(): Promise<void> {
  await authedFetch('/api/admin/eval/run', { method: 'POST' })
}

export async function apiExportEvalHtml(results: EvalResult[], completedAt: string | null): Promise<Blob> {
  const res = await authedFetch('/api/admin/eval/export/html', {
    method: 'POST',
    body: JSON.stringify({ results, completed_at: completedAt }),
  })
  return res.blob()
}
