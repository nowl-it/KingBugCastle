"use client"

import { useStatus, usePlayers, useServerSection } from "@/lib/api"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Users, Settings, HardDrive, Globe, Database, ScrollText, Crown, Coins, Gem, Heart, MemoryStick, Cpu, Server, Timer } from "lucide-react"
import Link from "next/link"

function Gauge({ label, value, sub, icon: Icon, color }: { label: string; value: string; sub?: string; icon: any; color: string }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{label}</CardTitle>
        <Icon className={`h-4 w-4 ${color}`} />
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
        {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
      </CardContent>
    </Card>
  )
}

export default function OverviewPage() {
  const { data: status, error } = useStatus()
  const { data: players } = usePlayers()
  const { data: sys } = useServerSection("system", 10000)

  if (!status && !error) return <div className="p-8 text-muted-foreground">Loading status...</div>
  if (error) return <div className="p-8 text-destructive">Failed to load system status.</div>

  const gd = status.gamedata || {}
  const list = Array.isArray(players) ? players : []
  const totals = list.reduce((acc, p: any) => ({
    gold: acc.gold + (p.gold || 0),
    cash: acc.cash + (p.cash || 0),
    heart: acc.heart + (p.heart || 0),
    posts: acc.posts + (p.counts?.posts || 0),
    cards: acc.cards + (p.counts?.cards || 0),
    items: acc.items + (p.counts?.items || 0),
  }), { gold: 0, cash: 0, heart: 0, posts: 0, cards: 0, items: 0 })

  const top = [...list].sort((a: any, b: any) => (b.level || 0) - (a.level || 0)).slice(0, 5)

  const sysData = sys?.ok ? sys.data : null
  const mem = sysData?.mem
  const disk = sysData?.disk
  const cpu = sysData?.cpu
  const loadPct = cpu && cpu.cores ? Math.min(100, Math.round((cpu.load1 / cpu.cores) * 100)) : null

  const metrics = [
    { label: "Players", value: status.players, icon: Users, color: "text-blue-400" },
    { label: "Server Version", value: status.version, icon: Settings, color: "text-violet-400" },
    { label: "Patch Folder", value: status.patchFolder, icon: HardDrive, color: "text-amber-400" },
    { label: "Multiplayer", value: status.multiplayer ? "Enabled" : "Disabled", icon: Globe, color: "text-emerald-400" },
  ]

  const hostMetrics = sysData ? [
    { label: "Memory", value: mem ? `${mem.used} / ${mem.total} MB` : "—", sub: mem ? `${mem.percent}% used` : undefined, icon: MemoryStick, color: "text-rose-400" },
    { label: "CPU load", value: loadPct !== null ? `${loadPct}%` : "—", sub: cpu ? `load 1m ${cpu.load1} · ${cpu.cores} cores` : undefined, icon: Cpu, color: "text-cyan-400" },
    { label: "Disk", value: disk ? `${disk.used} / ${disk.total} GB` : "—", sub: disk ? `${disk.percent}% used` : undefined, icon: Server, color: "text-lime-400" },
    { label: "Uptime", value: sysData.uptimeStr || "—", sub: sysData.startTime ? `since ${sysData.startTime}` : undefined, icon: Timer, color: "text-orange-400" },
  ] : []

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Overview</h1>
        <p className="text-muted-foreground">System telemetry and account totals.</p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {metrics.map((m, i) => (
          <Card key={i}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">{m.label}</CardTitle>
              <m.icon className={`h-4 w-4 ${m.color}`} />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{m.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      {sysData && (
        <div>
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-muted-foreground">Host</h2>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {hostMetrics.map((m, i) => <Gauge key={i} {...m} />)}
          </div>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Database className="w-5 h-5" /> Master Data</CardTitle>
            <CardDescription>Loaded from the local XML bundle.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground">Heroes (Units)</p>
                <p className="text-xl font-semibold">{gd.heroes || 0}</p>
              </div>
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground">Items</p>
                <p className="text-xl font-semibold">{gd.items || 0}</p>
              </div>
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground">Buffs</p>
                <p className="text-xl font-semibold">{gd.buffs || 0}</p>
              </div>
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground">Skills</p>
                <p className="text-xl font-semibold">{gd.skills || 0}</p>
              </div>
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground">Localization strings</p>
                <p className="text-xl font-semibold">{gd.strings || 0}</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Coins className="w-5 h-5" /> Economy (all players)</CardTitle>
            <CardDescription>Summed across every save on disk.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground flex items-center gap-1"><Crown className="w-3.5 h-3.5" /> Gold</p>
                <p className="text-xl font-semibold">{totals.gold.toLocaleString()}</p>
              </div>
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground flex items-center gap-1"><Gem className="w-3.5 h-3.5" /> Cash</p>
                <p className="text-xl font-semibold">{totals.cash.toLocaleString()}</p>
              </div>
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground flex items-center gap-1"><Heart className="w-3.5 h-3.5" /> Heart</p>
                <p className="text-xl font-semibold">{totals.heart.toLocaleString()}</p>
              </div>
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground flex items-center gap-1"><ScrollText className="w-3.5 h-3.5" /> Mail waiting</p>
                <p className="text-xl font-semibold">{totals.posts}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Users className="w-5 h-5" /> Highest-level accounts</CardTitle>
          <CardDescription>Top 5 by account level.</CardDescription>
        </CardHeader>
        <CardContent>
          {top.length === 0 && <p className="text-sm text-muted-foreground">No players yet.</p>}
          <ul className="divide-y divide-border">
            {top.map((p: any) => (
              <li key={p.id} className="flex items-center justify-between py-2">
                <div className="flex items-center gap-3">
                  <span className={`h-2 w-2 rounded-full ${p.active ? 'bg-green-500' : 'bg-muted-foreground/40'}`} />
                  <Link href={`/players`} className="text-sm font-medium hover:underline">{p.name}</Link>
                  <span className="text-xs text-muted-foreground font-mono">{p.id}</span>
                </div>
                <div className="flex items-center gap-4 text-sm">
                  <span className="text-muted-foreground">lv {p.level}</span>
                  <span className="text-muted-foreground font-mono">{p.gold?.toLocaleString()} gold</span>
                  <span className="text-muted-foreground">{p.counts?.cards} heroes</span>
                </div>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  )
}
