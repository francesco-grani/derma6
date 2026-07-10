import { createClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string
const supabasePublishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string

if (!supabaseUrl || !supabasePublishableKey) {
  throw new Error(
    'Missing VITE_SUPABASE_URL or VITE_SUPABASE_PUBLISHABLE_KEY. Set both in frontend/.env.',
  )
}

/**
 * Single shared Supabase client instance. Uses the current-generation
 * client-safe "publishable" key (format `sb_publishable_...`), not the
 * legacy JWT-format `anon` key.
 *
 * Import this everywhere the app needs Supabase auth/session access
 * (`lib/auth.tsx`, `lib/api.ts`, sign-up/sign-in pages) rather than
 * constructing additional clients.
 */
export const supabase = createClient(supabaseUrl, supabasePublishableKey)
