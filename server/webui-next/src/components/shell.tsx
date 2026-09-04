"use client"

import { useState } from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { useStatus, useWhoAmI, runMutation } from "@/lib/api"
import { LayoutDashboard, Users, UserRound, Package, Diamond, Mail, Server, Settings, LogOut, Menu, X, Database, ScrollText, HandHeart } from "lucide-react"

const NAV_ITEMS = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/players", label: "Players", icon: Users },
  { href: "/heroes", label: "Heroes", icon: UserRound },
  { href: "/items", label: "Items", icon: Package },
  { href: "/accessories", label: "Accessories", icon: Diamond },
  { href: "/gamedata", label: "Game Data", icon: Database },
  { href: "/mail", label: "Mail", icon: Mail },
  { href: "/requests", label: "Player Requests", icon: ScrollText },
  { href: "/donations", label: "Donations", icon: HandHeart },
  { href: "/server", label: "Server Diagnostics", icon: Server },
  { href: "/account", label: "Account Settings", icon: Settings },
]

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const { data: status } = useStatus()
  const { data: who, mutate: mutateWho } = useWhoAmI()
  const [navOpen, setNavOpen] = useState(false)

  const handleSignOut = async () => {
    await runMutation('/api/auth/logout', { method: 'POST' })
    localStorage.removeItem('admin_token')
    mutateWho()
  }

  const isSystemOnline = status?.players !== undefined

  const handleNav = () => setNavOpen(false)

  const nav = (
    <nav className="flex h-full flex-col px-4 py-6">
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
                onClick={handleNav}
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
  )

  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <header className="sticky top-0 z-50 flex h-16 shrink-0 items-center gap-x-3 border-b border-border bg-background px-4 sm:gap-x-6 sm:px-6 lg:px-8">
        <button
          onClick={() => setNavOpen(v => !v)}
          className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground lg:hidden"
          aria-label="Toggle navigation"
        >
          {navOpen ? <X size={20} /> : <Menu size={20} />}
        </button>

        <div className="flex flex-1 items-center gap-x-4 self-stretch lg:gap-x-6">
          <div className="flex items-center gap-2 font-semibold">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              K
            </div>
            <span className="hidden sm:inline">KGC Admin</span>
          </div>

          <div className="ml-auto flex items-center gap-x-4 lg:gap-x-6">
            <div className="flex items-center gap-2 text-sm font-medium">
              <div className={`h-2 w-2 rounded-full ${isSystemOnline ? 'bg-green-500' : 'bg-red-500'}`} />
              <span className="hidden text-muted-foreground md:inline">{isSystemOnline ? 'System Online' : 'System Offline'}</span>
            </div>
            {who?.user && (
              <div className="flex items-center gap-4 border-l border-border pl-4 lg:gap-6 lg:pl-6">
                <span className="hidden text-sm font-medium sm:inline">OP: {who.user}</span>
                <button
                  onClick={handleSignOut}
                  className="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
                  title="Sign out"
                >
                  <LogOut size={16} />
                  <span className="hidden md:inline">Sign out</span>
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      <div className="flex flex-1">
        {/* Mobile drawer */}
        {navOpen && (
          <div className="fixed inset-0 z-30 bg-black/50 lg:hidden" onClick={handleNav} />
        )}
        <aside className={`fixed bottom-0 left-0 top-16 z-40 w-64 shrink-0 border-r border-border bg-background transition-transform lg:sticky lg:top-16 lg:z-auto lg:h-[calc(100vh-4rem)] lg:translate-x-0 lg:transition-none lg:overflow-y-auto ${navOpen ? 'translate-x-0' : '-translate-x-full'}`}>
          {nav}
        </aside>

        <main className="min-w-0 flex-1 py-6 px-4 sm:px-6 lg:px-8 xl:px-12">
          {children}
        </main>
      </div>
    </div>
  )
}
