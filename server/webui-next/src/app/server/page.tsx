"use client"

import { useState } from "react"
import { useServerSection } from "@/lib/api"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { RefreshCw, Server } from "lucide-react"

const SECTIONS = [
  { id: "system", label: "System" },
  { id: "logs", label: "Logs" },
  { id: "routes", label: "Routes" },
  { id: "cdn", label: "CDN" },
  { id: "config", label: "Config" },
  { id: "info", label: "Info" },
]

export default function ServerPage() {
  const [section, setSection] = useState("system")
  const { data, error, isLoading, mutate } = useServerSection(section, 5000)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Server Diagnostics</h1>
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
          {data && !data.ok && <p className="py-8 text-sm text-muted-foreground">{data.error || "section unavailable"}</p>}
          {data?.ok && (
            <pre className="max-h-[60vh] overflow-auto rounded-md bg-muted/40 p-4 font-mono text-xs leading-relaxed">
              {JSON.stringify(data.data, null, 2)}
            </pre>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
