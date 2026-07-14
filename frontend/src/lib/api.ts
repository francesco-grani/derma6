import { supabase } from './supabaseClient'

/**
 * Typed fetch wrappers. Authenticated calls inject the bearer token from the
 * current Supabase session (supabase-js owns token storage/refresh — see
 * `lib/auth.tsx` — nothing here reads or writes an auth token via
 * `localStorage` anymore).
 */

/**
 * Resolves the current Supabase session's access token, or null when signed
 * out. Exported so call sites that can't route through `authedFetch()`
 * (e.g. `useStreamChat.ts`'s raw SSE `fetch()`, which needs a readable
 * stream rather than the parsed-JSON response `authedFetch()` returns) can
 * still attach the bearer token the same way.
 */
export async function getAccessToken(): Promise<string | null> {
  const { data } = await supabase.auth.getSession()
  return data.session?.access_token ?? null
}

/** sessionStorage keys that must never survive a sign-out, whichever path
 * triggers it (security-remediation Req 20.4; deepsec-revalidation follow-up
 * Task 80). Single source of truth — `lib/auth.tsx`'s `AuthProvider.logout()`
 * imports this instead of keeping its own copy, since both `logout()` and
 * `handleUnauthorized()` below sign the user out and both must clear it.
 * Kept in sync by hand with their single writers: SkinAnalysisPage.tsx's
 * SESSION_KEY, and the 'derma6:initial-message' handoff key written by
 * ProfilePage.tsx/RoutinesPage.tsx/SkinAnalysisPage.tsx and consumed by
 * ChatPage.tsx. */
export const SESSION_STORAGE_KEYS_TO_CLEAR_ON_SIGNOUT = [
  'derma6:skin-analysis',
  'derma6:initial-message',
]

function clearSignoutSessionStorage() {
  for (const key of SESSION_STORAGE_KEYS_TO_CLEAR_ON_SIGNOUT) {
    sessionStorage.removeItem(key)
  }
}

async function handleUnauthorized() {
  // The backend rejected the token as invalid/expired/malformed (Req 6.4);
  // drop the now-stale local Supabase session so the app stops retrying it.
  // This path bypasses `AuthProvider.logout()` entirely (it's called from
  // outside React, on any 401), so it must clear sessionStorage itself
  // rather than relying on `logout()` to have done it — the hard navigation
  // below already discards all in-memory state (QueryClient, React state),
  // but sessionStorage survives a navigation within the same tab (Task 80).
  await supabase.auth.signOut().catch(() => {})
  clearSignoutSessionStorage()
  window.location.replace('/login')
}

/** Error thrown by `authedFetch` on a non-2xx response, carrying the HTTP
 * status so callers can distinguish e.g. 412 "account setup incomplete"
 * from other failures (security-remediation Req 21.4/21.5) without
 * string-matching the message. */
export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function authedFetch(path: string, init: RequestInit = {}) {
  const token = await getAccessToken()
  const res = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers ?? {}),
    },
  })
  if (res.status === 401) {
    await handleUnauthorized()
    throw new ApiError('Session expired', 401)
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(err.detail ?? 'Request failed', res.status)
  }
  return res
}

// ── Auth ──────────────────────────────────────────────────────────────────

/**
 * POST /api/auth/complete-signup. Authenticated (security-remediation Req
 * 21.1) — Supabase issues no session while email confirmation is pending
 * (see Task 61 spike finding), so this can only be called once a real
 * session exists, i.e. after the user has verified their email and signed
 * in. Identity (`user_id`, `email`, `username`) is derived entirely from
 * the verified bearer token server-side; no body is sent. Idempotent — safe
 * to retry (`lib/auth.tsx`'s `AuthProvider` calls this automatically the
 * first time a session's profile fetch returns 412 "incomplete").
 */
export async function apiCompleteSignup(): Promise<{ user_id: string; username: string }> {
  const res = await authedFetch('/api/auth/complete-signup', { method: 'POST' })
  return res.json() as Promise<{ user_id: string; username: string }>
}

// ── Profile ───────────────────────────────────────────────────────────────

export interface UserProfile {
  user_id: string
  username: string
  skin_type: string | null
  skin_concerns: string[]
  has_shaving_routine: boolean | null
  beard_style: 'shave' | 'trim' | 'grow' | null
  location: string | null
  medical_flags: string[]
  onboarding_complete: boolean
  is_admin: boolean
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
  const token = await getAccessToken()
  const body = new FormData()
  body.append('file', file)
  const res = await fetch('/api/me/analyze-skin', {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body,
  })
  if (res.status === 401) {
    await handleUnauthorized()
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

// ── Product Finder ───────────────────────────────────────────────────────────

/** Field-for-field mirror of `backend/schemas.py`'s `ProductListing` (Req 9.7). */
export interface ProductListing {
  type: 'new' | 'used'
  title: string
  price: number | null
  currency: string | null
  source: string
  thumbnail_url: string | null
  listing_url: string
}

/** Field-for-field mirror of `backend/schemas.py`'s `ProductFindResponse` (Req 9.4, 9.9). */
export interface ProductFindResponse {
  listings: ProductListing[]
  retail_ok: boolean
  secondhand_ok: boolean
}

export type ProductFindSource = 'retail' | 'vinted' | 'kleinanzeigen'

export async function apiFindProduct(
  name: string,
  brand?: string,
  source?: ProductFindSource
): Promise<ProductFindResponse> {
  const params = new URLSearchParams({
    name,
    ...(brand ? { brand } : {}),
    ...(source ? { source } : {}),
  })
  const res = await authedFetch(`/api/products/find?${params.toString()}`)
  return res.json()
}

/**
 * Builds the `fetch()` `RequestInit`/URL pair for a streamed (`stream=true`)
 * `GET /api/products/find` request (product-finder-streaming Req 9.1-9.3).
 *
 * Deliberately not routed through `authedFetch()`: that helper returns
 * parsed JSON (`res.json()`), but the streaming caller (`useProductFind`,
 * `frontend/src/hooks/useProductFinder.ts`) needs the raw `Response` so it
 * can read `response.body.getReader()` itself — the same reason
 * `useStreamChat.ts` builds its own `fetch()` call for `POST /api/chat`
 * rather than going through a JSON-parsing helper. Bearer auth is still
 * attached via `getAccessToken()`, the same token-resolution path
 * `authedFetch()` itself uses, so `GET /api/products/find`'s existing
 * authentication requirement is unaffected by bypassing `authedFetch()`.
 * The native `EventSource` API is never used anywhere in this feature (Req
 * 9.3), since it cannot carry a custom `Authorization` header.
 */
export async function buildProductFindStreamRequest(
  name: string,
  brand?: string | null,
  source?: ProductFindSource
): Promise<{ url: string; init: RequestInit }> {
  const token = await getAccessToken()
  const params = new URLSearchParams({
    name,
    ...(brand ? { brand } : {}),
    ...(source ? { source } : {}),
    stream: 'true',
  })
  return {
    url: `/api/products/find?${params.toString()}`,
    init: {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    },
  }
}
