import { useState } from 'react'
import { Link, useNavigate } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { supabase } from '@/lib/supabaseClient'

type ResendState = 'idle' | 'sending' | 'sent' | 'error'

export default function SignInPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [unconfirmed, setUnconfirmed] = useState(false)
  const [loading, setLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [resendState, setResendState] = useState<ResendState>('idle')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setUnconfirmed(false)
    setResendState('idle')
    setLoading(true)
    try {
      const { error: signInError } = await supabase.auth.signInWithPassword({ email, password })
      if (signInError) {
        // Supabase's GoTrue-issued `email_not_confirmed` error code is the
        // reliable discriminator (Req 5.3) — fall back to a message match
        // in case an older/self-hosted GoTrue omits the `code` field.
        if (signInError.code === 'email_not_confirmed' || /email not confirmed/i.test(signInError.message)) {
          setUnconfirmed(true)
        } else {
          setError(signInError.message)
        }
        return
      }
      // `onAuthStateChange` in `lib/auth.tsx` picks up the new session;
      // nothing to set locally here.
      navigate({ to: '/chat' })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  async function handleResend() {
    setResendState('sending')
    try {
      const { error: resendError } = await supabase.auth.resend({ type: 'signup', email })
      if (resendError) throw resendError
      setResendState('sent')
    } catch {
      setResendState('error')
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: '#3E4D3F' }}>
      <Card className="w-full max-w-sm shadow-xl" style={{ background: '#2E3D2F', border: '1px solid #4B5A4C' }}>
        <CardHeader className="text-center pb-2">
          <img src="/Derma6_logo.png" alt="Derma6" className="mx-auto mb-2" style={{ height: 120, width: 'auto' }} />
          <p style={{ color: '#9EAD9E', fontSize: 13, marginTop: 4 }}>
            Skincare advice built for guys who are ready to get it right.
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

            {unconfirmed ? (
              // Distinguishable unverified-email state (Req 5.3), not just a
              // generic sign-in failure, with a one-click resend action.
              <div className="text-sm flex flex-col gap-1" style={{ color: '#C4933F' }}>
                <p>Your email hasn&apos;t been verified yet. Check your inbox for the verification link.</p>
                <button
                  type="button"
                  onClick={handleResend}
                  disabled={resendState === 'sending'}
                  style={{
                    color: '#9EAD9E', background: 'none', border: 'none', cursor: 'pointer',
                    textAlign: 'left', textDecoration: 'underline', fontSize: 13,
                  }}
                >
                  {resendState === 'sending'
                    ? 'Resending…'
                    : resendState === 'sent'
                    ? 'Verification email resent ✓'
                    : 'Resend verification email'}
                </button>
                {resendState === 'error' && (
                  <p style={{ color: '#C07070' }}>Could not resend — try again shortly.</p>
                )}
              </div>
            ) : (
              error && <p className="text-sm text-red-400">{error}</p>
            )}

            <Button
              type="submit"
              disabled={loading}
              style={{ background: '#7A9B7D', color: '#1C2520', fontWeight: 600 }}
              className="mt-1"
            >
              {loading ? 'Please wait…' : 'Sign in →'}
            </Button>
            <Link to="/signup" style={{ color: '#9EAD9E', fontSize: 13, textAlign: 'center' }}>
              Don&apos;t have an account? Sign up
            </Link>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
