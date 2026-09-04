"use client"

import { usePathname } from "next/navigation"
import { AuthGate } from "@/components/auth-gate"
import { PlayerProvider } from "@/components/player-context"
import { PortalLocaleProvider } from "@/components/portal-i18n"
import { AppShell } from "@/components/shell"

/** Keep the public player portal out of the administrator authentication shell. */
export function SiteShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const dedicatedPlayerPortal = typeof document !== "undefined"
    && document.documentElement.dataset.kgcPlayerPortal === "1"
  if (dedicatedPlayerPortal || pathname === "/player" || pathname.startsWith("/player/")) {
    return <PortalLocaleProvider>{children}</PortalLocaleProvider>
  }
  return (
    <AuthGate>
      <PlayerProvider>
        <AppShell>{children}</AppShell>
      </PlayerProvider>
    </AuthGate>
  )
}
