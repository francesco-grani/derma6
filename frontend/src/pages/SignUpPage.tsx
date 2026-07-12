import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { supabase } from '@/lib/supabaseClient'

/** Matches `CompleteSignupRequest`'s backend length validator (2-50 chars). */
const MIN_FIRST_NAME_LENGTH = 2

export default function SignUpPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [firstName, setFirstName] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [signedUp, setSignedUp] = useState(false)

  const canSubmit = firstName.trim().length >= MIN_FIRST_NAME_LENGTH

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!canSubmit) return
    setError('')
    setLoading(true)
    try {
      // The chosen display name travels as Supabase user_metadata (Req 21.1
      // / Task 61 spike finding): Supabase issues no session while email
      // confirmation is pending, so local provisioning can't happen from
      // this page at all — it runs at first authenticated login instead
      // (see `lib/auth.tsx`'s `AuthProvider`), reading the username back out
      // of the verified JWT's user_metadata claim.
      const { error: signUpError } = await supabase.auth.signUp({
        email,
        password,
        options: {
          emailRedirectTo: `${window.location.origin}/verify-email-callback`,
          data: { username: firstName.trim() },
        },
      })
      if (signUpError) throw signUpError
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
            <Input
              placeholder="First name"
              value={firstName}
              onChange={e => setFirstName(e.target.value)}
              required
              style={{ background: '#3E4D3F', border: '1px solid #4B5A4C', color: '#E0E8E0' }}
              className="placeholder:text-[#9EAD9E]"
            />
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
              disabled={loading || !canSubmit}
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
