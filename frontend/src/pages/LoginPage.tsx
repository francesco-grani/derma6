import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { apiLogin, apiRegister } from '@/lib/api'
import { useAuth } from '@/lib/auth'

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const fn = mode === 'login' ? apiLogin : apiRegister
      const data = await fn(username.trim(), password)
      login(data.access_token, data.username)
      navigate({ to: '/chat' })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: '#3E4D3F' }}>
      <Card className="w-full max-w-sm shadow-xl" style={{ background: '#2E3D2F', border: '1px solid #4B5A4C' }}>
        <CardHeader className="text-center pb-2">
          <img src="/Derma6_logo.png" alt="Derma6" className="mx-auto mb-2" style={{ height: 48, width: 'auto' }} />
          <p style={{ color: '#9EAD9E', fontSize: 13, marginTop: 4 }}>
            Skincare advice built for guys who are ready to get it right.
          </p>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <Input
              placeholder="Username"
              value={username}
              onChange={e => setUsername(e.target.value)}
              autoFocus
              required
              style={{ background: '#3E4D3F', border: '1px solid #4B5A4C', color: '#E0E8E0' }}
              className="placeholder:text-[#9EAD9E]"
            />
            <div className="flex flex-col gap-1">
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
              {mode === 'register' && (
                <p className="text-xs px-1" style={{ color: '#9EAD9E' }}>
                  Min 8 characters, at least one number or symbol (e.g. <span style={{ color: '#C4933F' }}>MyPass1!</span>)
                </p>
              )}
            </div>
            {error && (
              <p className="text-sm text-red-400">{error}</p>
            )}
            <Button
              type="submit"
              disabled={loading}
              style={{ background: '#7A9B7D', color: '#1C2520', fontWeight: 600 }}
              className="mt-1"
            >
              {loading ? 'Please wait…' : mode === 'login' ? 'Sign in →' : 'Create account →'}
            </Button>
            <button
              type="button"
              onClick={() => { setMode(m => m === 'login' ? 'register' : 'login'); setError(''); setShowPassword(false) }}
              style={{ color: '#9EAD9E', fontSize: 13, background: 'none', border: 'none', cursor: 'pointer', textAlign: 'center' }}
            >
              {mode === 'login' ? "Don't have an account? Register" : 'Already have an account? Sign in'}
            </button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
