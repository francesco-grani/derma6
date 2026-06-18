import { useQuery } from '@tanstack/react-query'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { apiGetAdminUsers } from '@/lib/api'
import { useAuth } from '@/lib/auth'

export default function AdminPage() {
  const { username } = useAuth()
  const { data: users, isLoading, error } = useQuery({
    queryKey: ['admin-users'],
    queryFn: apiGetAdminUsers,
    enabled: username === 'admin',
  })

  if (username !== 'admin') {
    return (
      <div className="flex-1 p-6" style={{ background: '#3E4D3F' }}>
        <p style={{ color: '#F0B8B8' }}>Access denied.</p>
      </div>
    )
  }

  if (isLoading) return <PageShell><p style={{ color: '#9EAD9E' }}>Loading users…</p></PageShell>
  if (error) return <PageShell><p style={{ color: '#F0B8B8' }}>Failed to load users.</p></PageShell>

  return (
    <PageShell>
      <h2 style={{ color: '#E0E8E0', fontSize: 20, fontWeight: 700, marginBottom: 20 }}>
        Admin — Users ({users?.length ?? 0})
      </h2>
      <div className="rounded-xl overflow-hidden" style={{ border: '1px solid #4B5A4C' }}>
        <Table>
          <TableHeader>
            <TableRow style={{ background: '#2E3D2F', borderColor: '#4B5A4C' }}>
              {['ID', 'Username', 'Skin Type', 'Concerns', 'Shaving', 'Medical Flags', 'Onboarding'].map(h => (
                <TableHead key={h} style={{ color: '#9EAD9E', fontSize: 11, letterSpacing: '0.06em' }}>{h}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {users?.map(u => (
              <TableRow key={u.id} style={{ borderColor: '#4B5A4C', background: '#3E4D3F' }}>
                <TableCell style={{ color: '#9EAD9E', fontSize: 13 }}>{u.id}</TableCell>
                <TableCell style={{ color: '#E0E8E0', fontSize: 13, fontWeight: 500 }}>{u.username}</TableCell>
                <TableCell style={{ color: '#9EAD9E', fontSize: 13 }}>{u.skin_type ?? '—'}</TableCell>
                <TableCell style={{ color: '#9EAD9E', fontSize: 13 }}>{u.skin_concerns ?? '—'}</TableCell>
                <TableCell style={{ color: '#9EAD9E', fontSize: 13 }}>{u.has_shaving_routine === null ? '—' : u.has_shaving_routine ? 'Yes' : 'No'}</TableCell>
                <TableCell style={{ color: '#9EAD9E', fontSize: 13 }}>{u.medical_flags ?? '—'}</TableCell>
                <TableCell style={{ fontSize: 13 }}>{u.onboarding_complete ? '✅' : '⏳'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </PageShell>
  )
}

function PageShell({ children }: { children: React.ReactNode }) {
  return <div className="flex-1 overflow-y-auto p-6" style={{ background: '#3E4D3F' }}>{children}</div>
}
