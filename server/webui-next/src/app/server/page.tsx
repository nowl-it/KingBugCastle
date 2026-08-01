"use client"

import { useState } from "react"
import { useServerSection } from "@/lib/api"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { RefreshCw, Server, Timer, Users, Route, Database, ScrollText, MemoryStick, Cpu, HardDrive, AlertTriangle, CheckCircle2 } from "lucide-react"

const SECTIONS = [
  { id: "system", label: "System" },
  { id: "logs", label: "Logs" },
  { id: "routes", label: "Routes" },
  { id: "cdn", label: "CDN" },
  { id: "config", label: "Config" },
  { id: "info", label: "Info" },
]

function SectionCard({ title, desc, children, right }: { title: string; desc?: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle className="text-base flex items-center gap-2"><Server className="h-4 w-4" /> {title}</CardTitle>
            {desc && <CardDescription>{desc}</CardDescription>}
          </div>
          {right}
        </div>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

function MiniStat({ icon: Icon, label, value, color }: { icon: any; label: string; value: any; color: string }) {
  return (
    <div className="flex items-center gap-3 rounded-md border border-border bg-muted/30 px-3 py-2">
      <Icon className={`h-4 w-4 ${color}`} />
      <div>
        <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</div>
        <div className="text-sm font-semibold font-mono">{value ?? "—"}</div>
      </div>
    </div>
  )
}

function JsonView({ data, maxH = "60vh" }: { data: any; maxH?: string }) {
  return (
    <pre className={`max-h-[${maxH}] overflow-auto rounded-md bg-muted/40 p-4 font-mono text-xs leading-relaxed`}>
      {JSON.stringify(data, null, 2)}
    </pre>
  )
}

export default function ServerPage() {
  const [section, setSection] = useState("system")
  const { data, error, isLoading, mutate } = useServerSection(section, 5000)

  const sys = data?.ok && data.data ? data.data : null
  const mem = sys?.mem
  const disk = sys?.disk
  const cpu = sys?.cpu
  const loadPct = cpu && cpu.cores ? Math.min(100, Math.round((cpu.load1 / cpu.cores) * 100)) : null

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Server Diagnostics</h1>
        <p className="text-muted-foreground">Read-only proxy of the game server's own admin API (:8080). Auto-refreshes every 5s.</p>
      </div>

      <div className="flex flex-wrap gap-2">
        {SECTIONS.map(s => (
          <button
            key={s.id}
            onClick={() => setSection(s.id)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${section === s.id ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:bg-muted/70"}`}
          >
            {s.label}
          </button>
        ))}
      </div>

      {sys && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
          <MiniStat icon={Timer} label="Uptime" value={sys.uptimeStr} color="text-orange-400" />
          <MiniStat icon={Users} label="Players" value={sys.playerCount} color="text-blue-400" />
          <MiniStat icon={Route} label="Routes" value={`${sys.routeCount} + ${sys.overrideCount} ovr`} color="text-violet-400" />
          <MiniStat icon={Database} label="CDN files" value={sys.cdmFiles} color="text-amber-400" />
          <MiniStat icon={ScrollText} label="Log lines" value={sys.logLines} color="text-cyan-400" />
          <MiniStat icon={MemoryStick} label="Memory" value={mem ? `${mem.used}/${mem.total} MB` : "—"} color="text-rose-400" />
          <MiniStat icon={Cpu} label="CPU load" value={loadPct !== null ? `${loadPct}% (1m)` : "—"} color="text-emerald-400" />
          <MiniStat icon={HardDrive} label="Disk" value={disk ? `${disk.used}/${disk.total} GB` : "—"} color="text-lime-400" />
        </div>
      )}

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2"><Server className="h-4 w-4" /> /api/server/{section}</CardTitle>
              <CardDescription>{data?.serverUrl || "proxying the game server"}</CardDescription>
            </div>
            <div className="flex items-center gap-3">
              {data && <Badge variant={data.ok ? "secondary" : "destructive"}>{data.ok ? `HTTP ${data.status}` : "down"}</Badge>}
              <button onClick={() => mutate()} className="text-muted-foreground hover:text-foreground"><RefreshCw className="h-4 w-4" /></button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading && !data && <p className="py-8 text-sm text-muted-foreground">Loading...</p>}
          {error && <p className="py-8 text-sm text-destructive">Failed: {error.message}</p>}
          {data && !data.ok && (
            <p className="py-8 flex items-center gap-2 text-sm text-muted-foreground">
              <AlertTriangle className="h-4 w-4 text-amber-400" /> {data.error || "section unavailable"}
            </p>
          )}
          {data?.ok && <SectionBody section={section} data={data.data} />}
        </CardContent>
      </Card>
    </div>
  )
}

function SectionBody({ section, data }: { section: string; data: any }) {
  if (section === "logs") {
    const lines = Array.isArray(data) ? data : []
    return (
      <div className="max-h-[60vh] overflow-auto rounded-md bg-black/60 p-3 font-mono text-xs leading-relaxed">
        {lines.map((line: string, i: number) => {
          const cls = line.includes("ERROR") || line.includes("Traceback")
            ? "text-red-400"
            : line.includes("WARN")
              ? "text-amber-400"
              : line.startsWith("[")
                ? "text-cyan-300"
                : "text-zinc-300"
          return <div key={i} className={`whitespace-pre-wrap ${cls}`}>{line}</div>
        })}
        {!lines.length && <p className="text-muted-foreground">No log lines.</p>}
      </div>
    )
  }

  if (section === "routes") {
    const routes = Array.isArray(data?.routes) ? data.routes : []
    return (
      <div>
        <div className="mb-2 text-sm text-muted-foreground">{data?.total ?? routes.length} routes registered</div>
        <div className="max-h-[60vh] overflow-auto rounded-md border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr><th className="px-3 py-2">Path</th><th className="px-3 py-2">Model</th><th className="px-3 py-2 text-right">Override</th></tr>
            </thead>
            <tbody className="divide-y divide-border">
              {routes.map((r: any) => (
                <tr key={r.path} className="hover:bg-muted/30">
                  <td className="px-3 py-1.5 font-mono text-xs">{r.path}</td>
                  <td className="px-3 py-1.5 font-mono text-xs text-muted-foreground">{r.model}</td>
                  <td className="px-3 py-1.5 text-right">
                    {r.overridden
                      ? <Badge variant="secondary" className="text-[10px]"><CheckCircle2 className="h-3 w-3 mr-1" /> direct handler</Badge>
                      : <span className="text-xs text-muted-foreground">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    )
  }

  if (section === "cdn") {
    const files = Array.isArray(data?.files) ? data.files : []
    const fmt = (n: number) => n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : n > 1024 ? `${(n / 1024).toFixed(1)} KB` : `${n} B`
    return (
      <div>
        <div className="mb-2 text-sm text-muted-foreground">{data?.total ?? files.length} files in the CDN bundle</div>
        <div className="max-h-[60vh] overflow-auto rounded-md border border-border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr><th className="px-3 py-2">File</th><th className="px-3 py-2 text-right">Size</th></tr>
            </thead>
            <tbody className="divide-y divide-border">
              {files.map((f: any) => (
                <tr key={f.name} className="hover:bg-muted/30">
                  <td className="px-3 py-1.5 font-mono text-xs">{f.name}</td>
                  <td className="px-3 py-1.5 text-right font-mono text-xs text-muted-foreground">{fmt(f.size)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    )
  }

  return <JsonView data={data} />
}
