"use client"

import { useStatus } from "@/lib/api"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Activity, Users, Globe, Settings, Database, HardDrive, Clock } from "lucide-react"

export default function OverviewPage() {
  const { data: status, error } = useStatus()

  if (!status && !error) return <div className="p-8 text-muted-foreground">Loading status...</div>
  if (error) return <div className="p-8 text-destructive">Failed to load system status.</div>

  const metrics = [
    { label: "Active Players", value: status.players, icon: Users },
    { label: "Server Version", value: status.version, icon: Settings },
    { label: "Patch Folder", value: status.patchFolder, icon: HardDrive },
    { label: "Multiplayer", value: status.multiplayer ? "Enabled" : "Disabled", icon: Globe },
    { label: "Auth Mode", value: status.authMode, icon: Settings },
  ]

  const gd = status.gamedata || {}

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Overview</h1>
        <p className="text-muted-foreground">System telemetry and active status.</p>
      </div>
      
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {metrics.map((m, i) => (
          <Card key={i}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">
                {m.label}
              </CardTitle>
              <m.icon className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{m.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Database className="w-5 h-5" /> Master Data</CardTitle>
            <CardDescription>Loaded from local XML bundle.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground">Units (Heroes)</p>
                <p className="text-xl font-semibold">{gd.units || 0}</p>
              </div>
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground">Items</p>
                <p className="text-xl font-semibold">{gd.items || 0}</p>
              </div>
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground">Equipments</p>
                <p className="text-xl font-semibold">{gd.equipment || 0}</p>
              </div>
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground">Cards (Relics)</p>
                <p className="text-xl font-semibold">{gd.cards || 0}</p>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Activity className="w-5 h-5" /> Live Tracker</CardTitle>
            <CardDescription>Battle tracker websockets</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">Connected Clients</span>
                <span className="text-xl font-bold">{status.trackerClients || 0}</span>
              </div>
              <div className="flex items-center justify-between border-t border-border pt-4">
                <span className="text-sm font-medium">ADB Serial</span>
                <span className="text-sm font-mono bg-muted px-2 py-1 rounded">{status.adbSerial || "localhost:5555"}</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
