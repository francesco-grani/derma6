import { useEffect, useState } from 'react'
import { Link } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { apiCheckUsername, apiCompleteSignup } from '@/lib/api'
import { supabase } from '@/lib/supabaseClient'

type Availability = 'idle' | 'checking' | 'available' | 'taken' | 'error'

/** Debounce delay for the live username-availability check (Req 4.2). */
const USERNAME_DEBOUNCE_MS = 400

/** Matches `CompleteSignupRequest`'s backend username-length validator (2-50 chars). */
const MIN_USERNAME_LENGTH = 2

export default function SignUpPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [username, setUsername] = useState('')
  // Result of the most recently *completed* availability check, tagged with
  // the candidate it applies to. Every display state is derived from this
  // plus the live `username` field below rather than stored directly, so
  // the effect only ever calls `setState` from inside its async callback
  // (a genuine "subscribe to an external system" case) and never
  // synchronously in the effect body itself.
  const [lastCheck, setLastCheck] = useState<{ candidate: string; result: 'available' | 'taken' | 'error' } | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [signedUp, setSignedUp] = useState(false)

  const candidate = username.trim()
  const candidateTooShort = candidate.length < MIN_USERNAME_LENGTH
  const availability: Availability =
    candidateTooShort ? 'idle'
    : lastCheck && lastCheck.candidate === candidate ? lastCheck.result
    : 'checking'

  // Live debounced username-availability check (Req 4.2): waits for the user
  // to stop typing before hitting the backend, and discards stale results if
  // the username changes again before the request resolves.
  useEffect(() => {
    if (candidateTooShort) return
    let cancelled = false
    const timer = setTimeout(() => {
      apiCheckUsername(candidate)
        .then(available => {
          if (cancelled) return
          setLastCheck({ candidate, result: available ? 'available' : 'taken' })
        })
        .catch(() => {
          if (cancelled) return
          setLastCheck({ candidate, result: 'error' })
        })
    }, USERNAME_DEBOUNCE_MS)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [candidate, candidateTooShort])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    // Belt-and-braces: the submit button is already disabled until
    // availability === 'available' (Req 4.3), but guard here too in case of
    // a fast Enter-key submit racing the debounce.
    if (availability !== 'available') return
    setError('')
    setLoading(true)
    try {
      const { data, error: signUpError } = await supabase.auth.signUp({ email, password })
      if (signUpError) throw signUpError
      const supabaseUserId = data.user?.id
      if (!supabaseUserId) throw new Error('Sign-up did not return a user id.')
      // Provision the local `users` row (Req 4.4). If this fails after the
      // auth identity already exists, surface the error clearly rather than
      // silently showing the "check your email" screen (Req 4.5).
      await apiCompleteSignup(supabaseUserId, email, username.trim())
      setSignedUp(true)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  if (signedUp) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: '#3E4D3F' }}>
        <Card className="w-full max-w-sm shadow-xl" style={{ background: '#2E3D2F', border: '1px solid #4B5A4C' }}>
          <CardHeader className="text-center pb-2">
            <img src="/Derma6_logo.png" alt="Derma6" className="mx-auto mb-2" style={{ height: 120, width: 'auto' }} />
          </CardHeader>
          <CardContent className="text-center flex flex-col gap-3">
            <p style={{ color: '#E0E8E0', fontWeight: 600 }}>Check your email to verify your account</p>
            <p className="text-sm" style={{ color: '#9EAD9E' }}>
              We sent a verification link to <strong>{email}</strong>. Once verified, you can sign in.
            </p>
            <Link to="/login" style={{ color: '#9EAD9E', fontSize: 13, textAlign: 'center' }}>
              Back to sign in
            </Link>
          </CardContent>
        </Card>
      </div>
    )
  }

  const availabilityHint =
    availability === 'checking' ? 'Checking availability…'
    : availability === 'available' ? 'Username available ✓'
    : availability === 'taken' ? 'Username already taken'
    : availability === 'error' ? 'Could not check availability — try again'
    : ''

  return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: '#3E4D3F' }}>
      <Card className="w-full max-w-sm shadow-xl" style={{ background: '#2E3D2F', border: '1px solid #4B5A4C' }}>
        <CardHeader className="text-center pb-2">
          <img src="/Derma6_logo.png" alt="Derma6" className="mx-auto mb-2" style={{ height: 120, width: 'auto' }} />
          <p style={{ color: '#9EAD9E', fontSize: 13, marginTop: 4 }}>
            Create your account to get started.
          </p>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <Input
              type="email"
              placeholder="Email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              autoFocus
              required
              style={{ background: '#3E4D3F', border: '1px solid #4B5A4C', color: '#E0E8E0' }}
              className="placeholder:text-[#9EAD9E]"
            />
            <div className="flex flex-col gap-1">
              <Input
                placeholder="Username"
                value={username}
                onChange={e => setUsername(e.target.value)}
                required
                style={{ background: '#3E4D3F', border: '1px solid #4B5A4C', color: '#E0E8E0' }}
                className="placeholder:text-[#9EAD9E]"
              />
              {availabilityHint && (
                <p
                  className="text-xs px-1"
                  style={{ color: availability === 'available' ? '#7A9B7D' : '#C4933F' }}
                >
                  {availabilityHint}
                </p>
              )}
            </div>
            <div className="relative">
              <Input
                type={showPassword ? 'text' : 'password'}
                placeholder="Password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                required
                style={{ background: '#3E4D3F', border: '1px solid #4B5A4C', color: '#E0E8E0', paddingRight: '2.5rem' }}
                className="placeholder:text-[#9EAD9E]"
              />
              <button
                type="button"
                onClick={() => setShowPassword(v => !v)}
                tabIndex={-1}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                style={{
                  position: 'absolute', right: '0.625rem', top: '50%', transform: 'translateY(-50%)',
                  background: 'none', border: 'none', cursor: 'pointer', color: '#9EAD9E', fontSize: 16, lineHeight: 1,
                }}
              >
                {showPassword ? '🙈' : '👁'}
              </button>
            </div>
            <p className="text-xs px-1" style={{ color: '#9EAD9E' }}>
              Min 8 characters, at least one number or symbol (e.g. <span style={{ color: '#C4933F' }}>MyPass1!</span>)
            </p>
            {error && (
              <p className="text-sm text-red-400">{error}</p>
            )}
            <Button
              type="submit"
              disabled={loading || availability !== 'available'}
              style={{ background: '#7A9B7D', color: '#1C2520', fontWeight: 600 }}
              className="mt-1"
            >
              {loading ? 'Please wait…' : 'Create account →'}
            </Button>
            <Link to="/login" style={{ color: '#9EAD9E', fontSize: 13, textAlign: 'center' }}>
              Already have an account? Sign in
            </Link>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
