import { useState } from 'react'
import { Link } from '@tanstack/react-router'
import { Card, CardContent, CardHeader } from '@/components/ui/card'

type Status = 'verified' | 'error'

interface VerifyResult {
  status: Status
  errorMessage: string
}

/**
 * Reads Supabase's `error`/`error_description` redirect params (present only
 * on a failed confirmation, e.g. an expired link) directly from the current
 * URL. Called once via `useState`'s lazy initializer below rather than in a
 * `useEffect` — the URL is available synchronously at render time and never
 * changes for the lifetime of this component, so there is no external
 * subscription to synchronize, just a one-time derivation.
 */
function parseVerifyResult(): VerifyResult {
  const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ''))
  const searchParams = new URLSearchParams(window.location.search)
  const description = hashParams.get('error_description') ?? searchParams.get('error_description')
  const errorCode = hashParams.get('error') ?? searchParams.get('error')
  if (errorCode || description) {
    return {
      status: 'error',
      errorMessage: description ? description.replace(/\+/g, ' ') : 'The verification link is invalid or has expired.',
    }
  }
  return { status: 'verified', errorMessage: '' }
}

/**
 * Route Supabase redirects the browser to after the user clicks the email
 * verification link (Req 5.2). `supabase-js`'s client (`detectSessionInUrl`,
 * on by default — see `lib/supabaseClient.ts`) has already parsed/consumed
 * any session tokens from the URL by the time this component mounts; this
 * component's job is purely to render a state the user understands.
 */
export default function VerifyEmailCallback() {
  const [{ status, errorMessage }] = useState(parseVerifyResult)

  return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: '#3E4D3F' }}>
      <Card className="w-full max-w-sm shadow-xl" style={{ background: '#2E3D2F', border: '1px solid #4B5A4C' }}>
        <CardHeader className="text-center pb-2">
          <img src="/Derma6_logo.png" alt="Derma6" className="mx-auto mb-2" style={{ height: 120, width: 'auto' }} />
        </CardHeader>
        <CardContent className="text-center flex flex-col gap-3">
          {status === 'verified' ? (
            <>
              <p data-testid="verify-status" style={{ color: '#E0E8E0', fontWeight: 600 }}>
                Email verified
              </p>
              <p className="text-sm" style={{ color: '#9EAD9E' }}>
                Email verified — you can sign in.
              </p>
              <Link to="/login" style={{ color: '#9EAD9E', fontSize: 13, textAlign: 'center' }}>
                Continue to sign in
              </Link>
            </>
          ) : (
            <>
              <p data-testid="verify-status" style={{ color: '#C4933F', fontWeight: 600 }}>
                Verification failed
              </p>
              <p className="text-sm" style={{ color: '#9EAD9E' }}>{errorMessage}</p>
              <Link to="/signup" style={{ color: '#9EAD9E', fontSize: 13, textAlign: 'center' }}>
                Sign up again
              </Link>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
