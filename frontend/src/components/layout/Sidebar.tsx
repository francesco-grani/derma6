import { useState } from 'react'
import { Link, useNavigate } from '@tanstack/react-router'
import { useAuth } from '@/lib/auth'
import { getToken } from '@/lib/api'
import { useProfile } from '@/hooks/useProfile'
import { Button } from '@/components/ui/button'

const NAV_LINKS = [
  { to: '/chat', label: 'Chat', icon: '💬' },
  { to: '/skin-analysis', label: 'Skin Analysis', icon: '🔬' },
  { to: '/profile', label: 'My Profile', icon: '👤' },
  { to: '/routines', label: 'Routines', icon: '📋' },
]

export default function Sidebar() {
  const { username, logout } = useAuth()
  const navigate = useNavigate()
  const { data: profile } = useProfile()
  const [logoutHovered, setLogoutHovered] = useState(false)
  const initials = username ? username.slice(0, 2).toUpperCase() : '?'

  // Enable export only when the user has some profile or skin data to include
  const hasData = !!profile && (
    profile.onboarding_complete ||
    profile.skin_type !== null ||
    profile.skin_concerns.length > 0
  )

  function handleLogout() {
    logout()
    navigate({ to: '/login' })
  }

  async function handleExport(format: 'html' | 'pdf') {
    const token = getToken()
    const res = await fetch(`/api/me/export?format=${format}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) return alert('Export failed')
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${username}_skincare_plan.${format}`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <aside
      className="flex flex-col h-screen w-56 shrink-0"
      style={{ background: '#2E3D2F', borderRight: '1px solid #4B5A4C' }}
    >
      {/* Logo */}
      <div className="px-5 pt-6 pb-4">
        <img src="/Derma6_logo.png" alt="Derma6" style={{ height: 36, width: 'auto' }} />
      </div>

      {/* Nav links */}
      <nav className="flex flex-col gap-1 px-3 flex-1">
        {NAV_LINKS.map(({ to, label, icon }) => (
          <Link
            key={to}
            to={to}
            className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors"
            style={{ color: '#E0E8E0' }}
            activeProps={{ style: { background: '#3E4D3F', color: '#E0E8E0' } }}
          >
            <span>{icon}</span>
            {label}
          </Link>
        ))}

        {username === 'admin' && (
          <Link
            to="/admin"
            className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors"
            style={{ color: '#9EAD9E' }}
            activeProps={{ style: { background: '#3E4D3F', color: '#E0E8E0' } }}
          >
            <span>⚙️</span> Admin
          </Link>
        )}
      </nav>

      {/* Export + user section */}
      <div className="px-3 pb-4 flex flex-col gap-2">
        <div className="flex gap-1">
          <Button
            size="sm"
            variant="outline"
            onClick={() => handleExport('html')}
            disabled={!hasData}
            className="flex-1 text-xs cursor-pointer disabled:cursor-not-allowed"
            style={{ borderColor: '#4B5A4C', color: hasData ? '#9EAD9E' : '#4B5A4C', background: 'transparent' }}
            title={hasData ? 'Download skincare plan as HTML' : 'Complete your profile first'}
          >
            ↓ HTML
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => handleExport('pdf')}
            disabled={!hasData}
            className="flex-1 text-xs cursor-pointer disabled:cursor-not-allowed"
            style={{ borderColor: '#4B5A4C', color: hasData ? '#9EAD9E' : '#4B5A4C', background: 'transparent' }}
            title={hasData ? 'Download skincare plan as PDF' : 'Complete your profile first'}
          >
            ↓ PDF
          </Button>
        </div>

        <div
          className="flex items-center gap-2 px-3 py-2 rounded-lg"
          style={{ background: '#3E4D3F' }}
        >
          <div
            className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
            style={{ background: '#7A9B7D', color: '#1C2520' }}
          >
            {initials}
          </div>
          <span className="text-sm truncate flex-1" style={{ color: '#E0E8E0' }}>{username}</span>
          <button
            onClick={handleLogout}
            onMouseEnter={() => setLogoutHovered(true)}
            onMouseLeave={() => setLogoutHovered(false)}
            title="Sign out"
            className="cursor-pointer rounded px-1.5 py-0.5 text-xs font-medium transition-all"
            style={{
              background: logoutHovered ? '#5A3E3E' : 'transparent',
              color: logoutHovered ? '#F0B8B8' : '#9EAD9E',
              border: logoutHovered ? '1px solid #7A4E4E' : '1px solid transparent',
            }}
          >
            {logoutHovered ? 'Sign out' : '↩'}
          </button>
        </div>
      </div>
    </aside>
  )
}
