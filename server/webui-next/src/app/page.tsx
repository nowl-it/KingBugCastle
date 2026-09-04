"use client"
import { useState, useEffect } from "react"
import { useQuery } from "@tanstack/react-query"
import { useStatus, usePlayers, useServerSection, fetcher } from "@/lib/api"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { type LucideIcon, Users, Settings, HardDrive, Globe, Database, ScrollText, Crown, Coins, Gem, Heart, MemoryStick, Cpu, Server, Timer, BarChart2, Activity, ListOrdered } from "lucide-react"
import Link from "next/link"
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts"

type PlayerSummary = { id: string; name: string; active?: boolean; level?: number; gold?: number; cash?: number; heart?: number; counts?: { posts?: number; cards?: number; items?: number } }
type HistoryPoint = { time: string; ccu: number }
type SystemHistoryPoint = { time: string; cpu: number; ram: number }
type ProcessInfo = { pid: number; name: string; cpu: number; mem: number }

function Gauge({ label, value, sub, icon: Icon, color }: { label: string; value: string; sub?: string; icon: LucideIcon; color: string }) {
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
  const { data: sys } = useServerSection("system", 2000)
  
  const { data: realtime } = useQuery({
    queryKey: ['/api/stats/realtime'],
    queryFn: () => fetcher('/api/stats/realtime'),
    refetchInterval: 2000
  })

  const [history, setHistory] = useState<HistoryPoint[]>([])
  const [sysHistory, setSysHistory] = useState<SystemHistoryPoint[]>([])

  useEffect(() => {
    if (realtime) {
      // The query result is an external polling source; preserve each sample for the chart.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setHistory(prev => {
        const next = [...prev, { time: new Date().toLocaleTimeString(), ccu: realtime.ccu }]
        if (next.length > 20) return next.slice(next.length - 20)
        return next
      })
    }
  }, [realtime])

  useEffect(() => {
    if (sys?.ok && sys.data) {
      // The query result is an external polling source; preserve each sample for the chart.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSysHistory(prev => {
        const d = new Date()
        const timeStr = `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}:${d.getSeconds().toString().padStart(2, '0')}`
        const next = [...prev, { 
          time: timeStr, 
          cpu: sys.data.cpu.load1,
          ram: sys.data.mem.percent
        }]
        if (next.length > 20) return next.slice(next.length - 20)
        return next
      })
    }
  }, [sys])

  const list = (Array.isArray(players) ? players : []) as PlayerSummary[]
  const totals = list.reduce((acc, p) => ({
    gold: acc.gold + (p.gold || 0),
    cash: acc.cash + (p.cash || 0),
    heart: acc.heart + (p.heart || 0),
    posts: acc.posts + (p.counts?.posts || 0),
    cards: acc.cards + (p.counts?.cards || 0),
    items: acc.items + (p.counts?.items || 0),
  }), { gold: 0, cash: 0, heart: 0, posts: 0, cards: 0, items: 0 })

  const top = [...list].sort((a, b) => (b.level || 0) - (a.level || 0)).slice(0, 5)

  const levelDistribution = (() => {
    const bins = [0, 0, 0, 0, 0] // 1-10, 11-20, 21-30, 31-40, 41-50
    list.forEach((p) => {
      const lv = p.level || 1
      if (lv <= 10) bins[0]++
      else if (lv <= 20) bins[1]++
      else if (lv <= 30) bins[2]++
      else if (lv <= 40) bins[3]++
      else bins[4]++
    })
    return [
      { name: "1-10", players: bins[0] },
      { name: "11-20", players: bins[1] },
      { name: "21-30", players: bins[2] },
      { name: "31-40", players: bins[3] },
      { name: "41-50", players: bins[4] },
    ]
  })()

  if (!status && !error) return <div className="p-8 text-muted-foreground">Loading status...</div>
  if (error) return <div className="p-8 text-destructive">Failed to load system status.</div>

  const gd = status.gamedata || {}

  const sysData = sys?.ok ? sys.data : null
  const mem = sysData?.mem
  const disk = sysData?.disk
  const cpu = sysData?.cpu
  const processes = (sysData?.processes || []) as ProcessInfo[]
  const loadPct = cpu && cpu.cores ? Math.min(100, Math.round((cpu.load1 / cpu.cores) * 100)) : null

  const metrics = [
    { label: "Players", value: status.players, icon: Users, color: "text-blue-400" },
    { label: "Server Version", value: status.version, icon: Settings, color: "text-violet-400" },
    { label: "Patch Folder", value: status.patchFolder, icon: HardDrive, color: "text-amber-400" },
    { label: "Multiplayer", value: status.multiplayer ? "Enabled" : "Disabled", icon: Globe, color: "text-emerald-400" },
  ]

  const hostMetrics = sysData ? [
    { label: "Memory", value: mem ? `${mem.used} / ${mem.total} MB` : "-", sub: mem ? `${mem.percent}% used` : undefined, icon: MemoryStick, color: "text-rose-400" },
    { label: "CPU load", value: loadPct !== null ? `${loadPct}%` : "-", sub: cpu ? `load 1m ${cpu.load1} · ${cpu.cores} cores` : undefined, icon: Cpu, color: "text-cyan-400" },
    { label: "Disk", value: disk ? `${disk.used} / ${disk.total} GB` : "-", sub: disk ? `${disk.percent}% used` : undefined, icon: Server, color: "text-lime-400" },
    { label: "Uptime", value: sysData.uptimeStr || "-", sub: sysData.startTime ? `since ${sysData.startTime}` : undefined, icon: Timer, color: "text-orange-400" },
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
          
          <div className="grid gap-4 md:grid-cols-3 mt-4">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2"><Cpu className="w-5 h-5" /> Realtime CPU Load</CardTitle>
                <CardDescription>System load average (1m).</CardDescription>
              </CardHeader>
              <CardContent className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={sysHistory} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="currentColor" className="opacity-20" />
                    <XAxis dataKey="time" fontSize={12} tickLine={false} axisLine={false} />
                    <YAxis allowDecimals={false} fontSize={12} tickLine={false} axisLine={false} />
                    <Tooltip contentStyle={{ backgroundColor: 'var(--background)', borderColor: 'var(--border)', borderRadius: '6px' }} />
                    <Line type="monotone" dataKey="cpu" stroke="currentColor" strokeWidth={2} dot={false} className="stroke-cyan-400" />
                  </LineChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2"><MemoryStick className="w-5 h-5" /> Realtime Memory</CardTitle>
                <CardDescription>System RAM utilization (%).</CardDescription>
              </CardHeader>
              <CardContent className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={sysHistory} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="currentColor" className="opacity-20" />
                    <XAxis dataKey="time" fontSize={12} tickLine={false} axisLine={false} />
                    <YAxis allowDecimals={false} fontSize={12} tickLine={false} axisLine={false} domain={[0, 100]} />
                    <Tooltip contentStyle={{ backgroundColor: 'var(--background)', borderColor: 'var(--border)', borderRadius: '6px' }} />
                    <Line type="monotone" dataKey="ram" stroke="currentColor" strokeWidth={2} dot={false} className="stroke-rose-400" />
                  </LineChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
            
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2"><ListOrdered className="w-5 h-5" /> Top Processes</CardTitle>
                <CardDescription>Highest CPU consumers.</CardDescription>
              </CardHeader>
              <CardContent>
                <ul className="divide-y divide-border">
                  <li className="flex items-center justify-between py-2 text-xs text-muted-foreground uppercase tracking-wider font-semibold">
                    <span className="w-20">PID</span>
                    <span className="flex-1">COMMAND</span>
                    <span className="w-16 text-right">CPU%</span>
                    <span className="w-16 text-right">MEM%</span>
                  </li>
                  {processes.map((p) => (
                    <li key={p.pid} className="flex items-center justify-between py-2 text-sm">
                      <span className="w-20 font-mono text-muted-foreground">{p.pid}</span>
                      <span className="flex-1 font-medium truncate pr-2">{p.name}</span>
                      <span className="w-16 text-right text-cyan-400">{p.cpu}</span>
                      <span className="w-16 text-right text-rose-400">{p.mem}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
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

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><BarChart2 className="w-5 h-5" /> Level Distribution</CardTitle>
            <CardDescription>Number of players per level range (real-time).</CardDescription>
          </CardHeader>
          <CardContent className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={levelDistribution} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="currentColor" className="opacity-20" />
                <XAxis dataKey="name" fontSize={12} tickLine={false} axisLine={false} />
                <YAxis allowDecimals={false} fontSize={12} tickLine={false} axisLine={false} />
                <Tooltip 
                  cursor={{ fill: 'currentColor', opacity: 0.1 }}
                  contentStyle={{ backgroundColor: 'var(--background)', borderColor: 'var(--border)', borderRadius: '6px' }} 
                />
                <Bar dataKey="players" fill="currentColor" radius={[4, 4, 0, 0]} className="fill-primary" />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Activity className="w-5 h-5" /> Realtime CCU</CardTitle>
            <CardDescription>Concurrent users active in the last 15 seconds.</CardDescription>
          </CardHeader>
          <CardContent className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={history} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="currentColor" className="opacity-20" />
                <XAxis dataKey="time" fontSize={12} tickLine={false} axisLine={false} />
                <YAxis allowDecimals={false} fontSize={12} tickLine={false} axisLine={false} />
                <Tooltip 
                  contentStyle={{ backgroundColor: 'var(--background)', borderColor: 'var(--border)', borderRadius: '6px' }} 
                />
                <Line type="monotone" dataKey="ccu" stroke="currentColor" strokeWidth={2} dot={false} className="stroke-primary" />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Users className="w-5 h-5" /> Highest-level accounts</CardTitle>
            <CardDescription>Top 5 by account level.</CardDescription>
          </CardHeader>
          <CardContent>
          {top.length === 0 && <p className="text-sm text-muted-foreground">No players yet.</p>}
          <ul className="divide-y divide-border">
            {top.map((p) => (
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
    </div>
  )
}
