import { Outlet } from '@tanstack/react-router'
import { useAuth } from '@/lib/auth'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import Sidebar from '@/components/layout/Sidebar'
import { ProductFinderProvider } from '@/components/products/ProductFinderProvider'
import { ProductFinderPopover } from '@/components/products/ProductFinderPopover'

export default function AppLayout() {
  // security-remediation Req 21.4/21.5: a verified session whose local
  // signup provisioning failed even after AuthProvider's automatic retry
  // gets a distinguishable recovery screen here, instead of proceeding into
  // Sidebar/Outlet as if the account were ready.
  const { provisioningError, retryProvisioning } = useAuth()

  if (provisioningError) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: '#3E4D3F' }}>
        <Card className="w-full max-w-sm shadow-xl" style={{ background: '#2E3D2F', border: '1px solid #4B5A4C' }}>
          <CardHeader className="text-center pb-2">
            <img src="/Derma6_logo.png" alt="Derma6" className="mx-auto mb-2" style={{ height: 120, width: 'auto' }} />
          </CardHeader>
          <CardContent className="text-center flex flex-col gap-3">
            <p style={{ color: '#C4933F', fontWeight: 600 }}>Account setup incomplete</p>
            <p className="text-sm" style={{ color: '#9EAD9E' }}>{provisioningError}</p>
            <Button
              onClick={() => void retryProvisioning()}
              style={{ background: '#7A9B7D', color: '#1C2520', fontWeight: 600 }}
            >
              Retry
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    // Mounted once, wrapping the whole app shell, so any descendant page can
    // call useProductFinderTarget()/render FindProductButton (Task 16/18) and
    // share the single global popover below (design.md's "one instance with
    // dynamic anchor" decision — Req 3.1, 3.5).
    <ProductFinderProvider>
      <div className="flex h-screen overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-hidden flex flex-col">
          <Outlet />
        </main>
        {/* Sibling to page content, not nested inside it, so it's
            portal-rendered and never clipped by a page's own overflow
            containers (Task 19/20). */}
        <ProductFinderPopover />
      </div>
    </ProductFinderProvider>
  )
}
