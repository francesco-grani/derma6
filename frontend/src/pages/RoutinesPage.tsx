import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { useRoutines, useDeleteRoutine, useRenameRoutine } from '@/hooks/useRoutines'
import { useSession } from '@/lib/sessionContext'
import type { Routine } from '@/lib/api'

const CATEGORY_LABELS: Record<string, string> = {
  cleanser: 'CLEANSE', toner: 'BALANCE', serum: 'TREATMENT',
  moisturiser: 'MOISTURE', moisturizer: 'MOISTURE',
  spf: 'PROTECT', sunscreen: 'PROTECT',
}

function categoryLabel(ingredient: string) {
  return CATEGORY_LABELS[ingredient.toLowerCase()] ?? 'STEP'
}

export default function RoutinesPage() {
  const { data: routines, isLoading } = useRoutines()
  const deleteRoutine = useDeleteRoutine()
  const renameRoutine = useRenameRoutine()
  const navigate = useNavigate()
  const { startNewSession } = useSession()

  const [renameTarget, setRenameTarget] = useState<string | null>(null)
  const [newName, setNewName] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)
  const [enhanceTarget, setEnhanceTarget] = useState<Routine | null>(null)
  const [enhanceGoal, setEnhanceGoal] = useState('')

  if (isLoading) return <PageShell><p style={{ color: '#9EAD9E' }}>Loading routines…</p></PageShell>

  if (!routines || routines.length === 0) {
    return (
      <PageShell>
        <p style={{ color: '#9EAD9E' }}>No routines saved yet. Ask the assistant to build you one!</p>
      </PageShell>
    )
  }

  async function confirmRename() {
    if (!renameTarget || !newName.trim()) return
    await renameRoutine.mutateAsync({ oldName: renameTarget, newName: newName.trim() })
    setRenameTarget(null)
    setNewName('')
  }

  async function confirmDelete() {
    if (!deleteTarget) return
    await deleteRoutine.mutateAsync(deleteTarget)
    setDeleteTarget(null)
  }

  return (
    <PageShell>
      <h2 style={{ color: '#E0E8E0', fontSize: 20, fontWeight: 700, marginBottom: 20 }}>My Routines</h2>

      <div className="flex flex-col gap-8">
        {routines.map((routine: Routine) => (
          <div key={routine.name}>
            <div className="flex items-center justify-between mb-3">
              <h3 style={{ color: '#E0E8E0', fontSize: 17, fontWeight: 600 }}>{routine.name}</h3>
              <div className="flex gap-2">
                <Button size="sm" variant="outline"
                  className="cursor-pointer"
                  style={{ borderColor: '#4B5A4C', color: '#9EAD9E', background: 'transparent', fontSize: 12 }}
                  onClick={() => { setRenameTarget(routine.name); setNewName(routine.name) }}>
                  Rename
                </Button>
                <Button size="sm" variant="outline"
                  className="cursor-pointer"
                  style={{ borderColor: '#7A4E4E', color: '#F0B8B8', background: 'transparent', fontSize: 12 }}
                  onClick={() => setDeleteTarget(routine.name)}>
                  Delete
                </Button>
              </div>
            </div>

            <div className="flex flex-col gap-2">
              {routine.steps.map((step, i) => (
                <div key={i} className="flex items-start gap-3 p-3 rounded-xl"
                  style={{ background: '#fff', borderLeft: '4px solid #C4933F' }}>
                  <div className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
                    style={{ background: '#2E3D2F', color: '#fff' }}>
                    {i + 1}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex justify-between items-center">
                      <span style={{ color: '#1C2520', fontWeight: 600, fontSize: 14 }}>
                        {step.ingredient.charAt(0).toUpperCase() + step.ingredient.slice(1)}
                      </span>
                      <span style={{ color: '#9EAD9E', fontSize: 11, letterSpacing: '0.08em', flexShrink: 0, marginLeft: 8 }}>
                        {categoryLabel(step.ingredient)}
                      </span>
                    </div>
                    {(step.product_name || step.budget_product) && (
                      <div className="flex flex-col gap-1 mt-2">
                        {step.product_name && (
                          <div className="flex items-center gap-1.5">
                            <span className="flex-shrink-0 text-xs px-1.5 py-0.5 rounded font-medium"
                              style={{ background: '#FFF3DC', color: '#A0742A', fontSize: 10, letterSpacing: '0.04em' }}>
                              ⭐ pick
                            </span>
                            <span style={{ color: '#3A2A0A', fontSize: 12 }} className="truncate">
                              {step.product_name}
                            </span>
                          </div>
                        )}
                        {step.budget_product && (
                          <div className="flex items-center gap-1.5">
                            <span className="flex-shrink-0 text-xs px-1.5 py-0.5 rounded font-medium"
                              style={{ background: '#E8F0E8', color: '#2E5A31', fontSize: 10, letterSpacing: '0.04em' }}>
                              💚 budget
                            </span>
                            <span style={{ color: '#1C3D1E', fontSize: 12 }} className="truncate">
                              {step.budget_product}
                            </span>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>

            <Button
              size="sm" variant="outline"
              className="mt-3 cursor-pointer"
              style={{ borderColor: '#4B5A4C', color: '#9EAD9E', background: 'transparent', fontSize: 12 }}
              onClick={() => { setEnhanceTarget(routine); setEnhanceGoal('') }}
            >
              ✨ Enhance this routine
            </Button>
          </div>
        ))}
      </div>

      {/* Rename dialog */}
      <Dialog open={!!renameTarget} onOpenChange={() => setRenameTarget(null)}>
        <DialogContent style={{ background: '#2E3D2F', border: '1px solid #4B5A4C' }}>
          <DialogHeader>
            <DialogTitle style={{ color: '#E0E8E0' }}>Rename routine</DialogTitle>
          </DialogHeader>
          <Input
            value={newName}
            onChange={e => setNewName(e.target.value)}
            style={{ background: '#3E4D3F', border: '1px solid #4B5A4C', color: '#E0E8E0' }}
            onKeyDown={e => e.key === 'Enter' && confirmRename()}
          />
          <DialogFooter>
            <Button variant="outline" className="cursor-pointer" onClick={() => setRenameTarget(null)}
              style={{ borderColor: '#4B5A4C', color: '#9EAD9E', background: 'transparent' }}>
              Cancel
            </Button>
            <Button className="cursor-pointer" onClick={confirmRename} disabled={renameRoutine.isPending}
              style={{ background: '#7A9B7D', color: '#1C2520' }}>
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete confirmation dialog */}
      <Dialog open={!!deleteTarget} onOpenChange={() => setDeleteTarget(null)}>
        <DialogContent style={{ background: '#2E3D2F', border: '1px solid #4B5A4C' }}>
          <DialogHeader>
            <DialogTitle style={{ color: '#E0E8E0' }}>Delete "{deleteTarget}"?</DialogTitle>
          </DialogHeader>
          <p style={{ color: '#9EAD9E', fontSize: 14 }}>This cannot be undone.</p>
          <DialogFooter>
            <Button variant="outline" className="cursor-pointer" onClick={() => setDeleteTarget(null)}
              style={{ borderColor: '#4B5A4C', color: '#9EAD9E', background: 'transparent' }}>
              Cancel
            </Button>
            <Button className="cursor-pointer" onClick={confirmDelete} disabled={deleteRoutine.isPending}
              style={{ background: '#7A4E4E', color: '#F0B8B8', borderColor: '#7A4E4E' }}>
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Enhance dialog */}
      <Dialog open={!!enhanceTarget} onOpenChange={() => setEnhanceTarget(null)}>
        <DialogContent style={{ background: '#2E3D2F', border: '1px solid #4B5A4C' }}>
          <DialogHeader>
            <DialogTitle style={{ color: '#E0E8E0' }}>Enhance "{enhanceTarget?.name}"</DialogTitle>
          </DialogHeader>
          <p style={{ color: '#9EAD9E', fontSize: 13 }}>What would you like to improve? (optional)</p>
          <Input
            value={enhanceGoal}
            onChange={e => setEnhanceGoal(e.target.value)}
            placeholder="e.g. add anti-aging, improve hydration…"
            style={{ background: '#3E4D3F', border: '1px solid #4B5A4C', color: '#E0E8E0' }}
            onKeyDown={async e => {
              if (e.key === 'Enter' && enhanceTarget) {
                const target = enhanceTarget
                const goal = enhanceGoal
                setEnhanceTarget(null)
                const steps = target.steps.map(s => s.ingredient).join(', ')
                const msg = `Please enhance my "${target.name}" routine. Current steps: ${steps}.${goal ? ` I'd like to focus on: ${goal}.` : ' Suggest improvements based on my skin profile.'}`
                await startNewSession()
                sessionStorage.setItem('derma6:initial-message', msg)
                navigate({ to: '/chat' })
              }
            }}
          />
          <DialogFooter>
            <Button variant="outline" className="cursor-pointer" onClick={() => setEnhanceTarget(null)}
              style={{ borderColor: '#4B5A4C', color: '#9EAD9E', background: 'transparent' }}>
              Cancel
            </Button>
            <Button
              className="cursor-pointer"
              disabled={!enhanceTarget}
              style={{ background: '#7A9B7D', color: '#1C2520' }}
              onClick={async () => {
                if (!enhanceTarget) return
                const target = enhanceTarget
                const goal = enhanceGoal
                setEnhanceTarget(null)
                const steps = target.steps.map(s => s.ingredient).join(', ')
                const msg = `Please enhance my "${target.name}" routine. Current steps: ${steps}.${goal ? ` I'd like to focus on: ${goal}.` : ' Suggest improvements based on my skin profile.'}`
                await startNewSession()
                sessionStorage.setItem('derma6:initial-message', msg)
                navigate({ to: '/chat' })
              }}
            >
              Enhance ✨
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PageShell>
  )
}

function PageShell({ children }: { children: React.ReactNode }) {
  return <div className="flex-1 overflow-y-auto p-6" style={{ background: '#3E4D3F' }}>{children}</div>
}
