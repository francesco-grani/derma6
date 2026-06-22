import { useState } from 'react'
import { Link, useNavigate } from '@tanstack/react-router'
import { useAuth } from '@/lib/auth'
import { useSession } from '@/lib/sessionContext'
import { getToken } from '@/lib/api'
import { useProfile } from '@/hooks/useProfile'
import { useSessions, useDeleteSession } from '@/hooks/useSessions'
import { Button } from '@/components/ui/button'

const NAV_LINKS = [
  { to: '/skin-analysis', label: 'Skin Analysis', icon: '🔬' },
  { to: '/profile', label: 'My Profile', icon: '👤' },
  { to: '/routines', label: 'Routines', icon: '📋' },
]

function formatDate(iso: string) {
  const d = new Date(iso)
  const now = new Date()
  const diffDays = Math.floor((now.getTime() - d.getTime()) / 86_400_000)
  if (diffDays === 0) return 'Today'
  if (diffDays === 1) return 'Yesterday'
  if (diffDays < 7) return `${diffDays}d ago`
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export default function Sidebar() {
  const { username, logout } = useAuth()
  const navigate = useNavigate()
  const { data: profile } = useProfile()
  const { sessionId, setSessionId, startNewSession } = useSession()
  const { data: sessions = [] } = useSessions()
  const deleteSession = useDeleteSession()
  const [logoutHovered, setLogoutHovered] = useState(false)
  const [hoveredSession, setHoveredSession] = useState<string | null>(null)
  const initials = username ? username.slice(0, 2).toUpperCase() : '?'

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

  async function handleNewChat() {
    const id = await startNewSession()
    navigate({ to: '/chat' })
    return id
  }

  function handleSelectSession(id: string) {
    setSessionId(id)
    navigate({ to: '/chat' })
  }

  async function handleDeleteSession(e: React.MouseEvent, id: string) {
    e.stopPropagation()
    await deleteSession.mutateAsync(id)
    if (sessionId === id) {
      // Switch away from deleted session
      const remaining = sessions.filter(s => s.session_id !== id)
      if (remaining.length > 0) {
        setSessionId(remaining[0].session_id)
      } else {
        const newId = await startNewSession()
        navigate({ to: '/chat' })
        return newId
      }
    }
  }

  return (
    <aside
      className="flex flex-col h-screen w-56 shrink-0"
      style={{ background: '#2E3D2F', borderRight: '1px solid #4B5A4C' }}
    >
      {/* Logo */}
      <div className="px-5 pt-6 pb-4">
        <img src="/Derma6_logo.png" alt="Derma6" style={{ height: 52, width: 'auto' }} />
      </div>

      {/* Chat section: button + session list */}
      <div className="px-3 mb-1">
        <div className="flex items-center justify-between mb-1">
          <button
            onClick={() => handleSelectSession(sessions[0]?.session_id ?? '') || handleNewChat()}
            className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium flex-1 text-left transition-colors"
            style={{ color: '#E0E8E0' }}
          >
            <span>💬</span> Chat
          </button>
          <button
            onClick={handleNewChat}
            title="New chat"
            className="flex items-center justify-center w-7 h-7 rounded-lg text-sm transition-colors hover:opacity-80 cursor-pointer"
            style={{ color: '#9EAD9E', background: '#3E4D3F', border: '1px solid #4B5A4C' }}
          >
            +
          </button>
        </div>

        {/* Session list */}
        {sessions.length > 0 && (
          <div
            className="flex flex-col gap-0.5 overflow-y-auto"
            style={{ maxHeight: 220 }}
          >
            {sessions.map(s => {
              const isActive = s.session_id === sessionId
              const isHovered = hoveredSession === s.session_id
              return (
                <div
                  key={s.session_id}
                  className="flex items-center gap-1 px-2 py-1.5 rounded-lg cursor-pointer group"
                  style={{
                    background: isActive ? '#3E4D3F' : 'transparent',
                    minWidth: 0,
                  }}
                  onClick={() => handleSelectSession(s.session_id)}
                  onMouseEnter={() => setHoveredSession(s.session_id)}
                  onMouseLeave={() => setHoveredSession(null)}
                >
                  <div className="flex flex-col flex-1 min-w-0">
                    <span
                      className="text-xs truncate"
                      style={{ color: isActive ? '#E0E8E0' : '#9EAD9E' }}
                    >
                      {s.title ?? 'New chat'}
                    </span>
                    <span className="text-xs" style={{ color: '#5A6A5B', fontSize: 10 }}>
                      {formatDate(s.updated_at)}
                    </span>
                  </div>
                  {isHovered && (
                    <button
                      onClick={e => handleDeleteSession(e, s.session_id)}
                      className="shrink-0 text-xs rounded px-1 hover:opacity-80 cursor-pointer"
                      style={{ color: '#C07070', background: 'none', border: 'none' }}
                      title="Delete session"
                    >
                      ✕
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Other nav links */}
      <nav className="flex flex-col gap-1 px-3 flex-1">
        <div className="my-2" style={{ borderTop: '1px solid #4B5A4C' }} />
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
