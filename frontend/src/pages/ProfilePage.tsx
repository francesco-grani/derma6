import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useProfile } from '@/hooks/useProfile'

export default function ProfilePage() {
  const { data: profile, isLoading, error } = useProfile()

  if (isLoading) return <PageShell><p style={{ color: '#9EAD9E' }}>Loading profile…</p></PageShell>
  if (error || !profile) return <PageShell><p style={{ color: '#F0B8B8' }}>Could not load profile.</p></PageShell>

  return (
    <PageShell>
      <h2 style={{ color: '#E0E8E0', fontSize: 20, fontWeight: 700, marginBottom: 20 }}>My Profile</h2>

      <div className="grid grid-cols-2 gap-4 mb-6">
        <MetricCard label="Skin Type" value={profile.skin_type ? profile.skin_type.charAt(0).toUpperCase() + profile.skin_type.slice(1) : '—'} />
        <MetricCard label="Shaving Routine" value={profile.has_shaving_routine === null ? '—' : profile.has_shaving_routine ? 'Yes' : 'No'} />

        <Card style={{ background: '#2E3D2F', border: '1px solid #4B5A4C' }}>
          <CardHeader className="pb-1 pt-3 px-4">
            <CardTitle className="text-xs font-semibold tracking-widest uppercase" style={{ color: '#9EAD9E' }}>Skin Concerns</CardTitle>
          </CardHeader>
          <CardContent className="pb-3 px-4">
            {profile.skin_concerns.length > 0
              ? <div className="flex flex-wrap gap-1">{profile.skin_concerns.map(c => <Badge key={c} variant="secondary">{c}</Badge>)}</div>
              : <span style={{ color: '#9EAD9E', fontSize: 14 }}>None recorded yet</span>}
          </CardContent>
        </Card>

        <MetricCard label="Onboarding" value={profile.onboarding_complete ? '✅ Complete' : '⏳ In progress'} />
      </div>

      {profile.medical_flags.length > 0 && (
        <div className="mb-6 p-4 rounded-xl" style={{ background: '#5A3E3E', border: '1px solid #7A4E4E' }}>
          <p style={{ color: '#F0B8B8', fontSize: 13 }}>
            ⚠️ Medical flags: {profile.medical_flags.join(', ')}. Please consult a dermatologist before making changes to your routine.
          </p>
        </div>
      )}
    </PageShell>
  )
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <Card style={{ background: '#2E3D2F', border: '1px solid #4B5A4C' }}>
      <CardHeader className="pb-1 pt-3 px-4">
        <CardTitle className="text-xs font-semibold tracking-widest uppercase" style={{ color: '#9EAD9E' }}>{label}</CardTitle>
      </CardHeader>
      <CardContent className="pb-3 px-4">
        <span style={{ color: '#E0E8E0', fontSize: 15, fontWeight: 500 }}>{value}</span>
      </CardContent>
    </Card>
  )
}

function PageShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex-1 overflow-y-auto p-6" style={{ background: '#3E4D3F' }}>
      {children}
    </div>
  )
}
