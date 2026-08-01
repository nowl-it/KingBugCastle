"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useStatus, useWhoAmI, runMutation } from "@/lib/api"
import { LayoutDashboard, Users, UserRound, Package, Diamond, Mail, Server, Settings, LogOut } from "lucide-react"

const NAV_ITEMS = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/players", label: "Players", icon: Users },
  { href: "/heroes", label: "Heroes", icon: UserRound },
  { href: "/items", label: "Items", icon: Package },
  { href: "/accessories", label: "Accessories", icon: Diamond },
  { href: "/mail", label: "Mail", icon: Mail },
  { href: "/server", label: "Server Diagnostics", icon: Server },
  { href: "/account", label: "Account Settings", icon: Settings },
]

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const { data: status } = useStatus()
  const { data: who, mutate: mutateWho } = useWhoAmI()

  const handleSignOut = async () => {
    await runMutation('/api/auth/logout', { method: 'POST' })
    localStorage.removeItem('admin_token')
    mutateWho()
  }

  const isSystemOnline = status?.players !== undefined

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <header className="sticky top-0 z-40 flex h-16 shrink-0 items-center gap-x-4 border-b border-border bg-background px-4 sm:gap-x-6 sm:px-6 lg:px-8">
        <div className="flex flex-1 items-center gap-x-4 self-stretch lg:gap-x-6">
          <div className="flex items-center gap-2 font-semibold">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              K
            </div>
            <span>KGC Admin</span>
          </div>
          
          <div className="ml-auto flex items-center gap-x-4 lg:gap-x-6">
            <div className="flex items-center gap-2 text-sm font-medium">
              <div className={`h-2 w-2 rounded-full ${isSystemOnline ? 'bg-green-500' : 'bg-red-500'}`} />
              <span className="text-muted-foreground">{isSystemOnline ? 'System Online' : 'System Offline'}</span>
            </div>
            {who?.user && (
              <div className="flex items-center gap-4 border-l border-border pl-4 lg:pl-6">
                <span className="text-sm font-medium">OP: {who.user}</span>
                <button 
                  onClick={handleSignOut}
                  className="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
                >
                  <LogOut size={16} />
                  Sign out
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      <div className="flex flex-1">
        <aside className="w-64 shrink-0 border-r border-border bg-muted/20">
          <nav className="flex flex-1 flex-col px-4 py-6">
            <div className="mb-4 px-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Navigation
            </div>
            <ul className="flex flex-1 flex-col gap-y-1">
              {NAV_ITEMS.map((item) => {
                const isActive = pathname === item.href
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className={`group flex gap-x-3 rounded-md p-2 text-sm leading-6 font-medium transition-colors ${
                        isActive 
                          ? 'bg-primary text-primary-foreground' 
                          : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                      }`}
                    >
                      <item.icon className={`h-5 w-5 shrink-0 ${isActive ? 'text-primary-foreground' : 'text-muted-foreground group-hover:text-foreground'}`} />
                      {item.label}
                    </Link>
                  </li>
                )
              })}
            </ul>
          </nav>
        </aside>

        <main className="flex-1 py-8 px-8 xl:px-12">
          {children}
        </main>
      </div>
    </div>
  )
}
