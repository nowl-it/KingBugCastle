"use client"

import { useState } from "react"
import { runMutation } from "@/lib/api"
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Terminal, Database, ShieldAlert, FileJson } from "lucide-react"

export default function ServerPage() {
  const [busy, setBusy] = useState(false)
  const [response, setResponse] = useState("")
  const [code, setCode] = useState("")

  const runMaintenance = async (action: string) => {
    setBusy(true)
    try {
      if (action === 'reload_config') {
        const res = await runMutation('/api/server/reload_config', { method: 'POST' }, "Config reloaded")
        setResponse(JSON.stringify(res, null, 2))
      } else if (action === 'dump_db') {
        const res = await runMutation('/api/server/dump_db', { method: 'POST' }, "Database dumped")
        setResponse(JSON.stringify(res, null, 2))
      } else if (action === 'clear_cache') {
        const res = await runMutation('/api/server/clear_cache', { method: 'POST' }, "Cache cleared")
        setResponse(JSON.stringify(res, null, 2))
      }
    } catch (e: any) {
      setResponse(`Error: ${e.message}`)
    } finally {
      setBusy(false)
    }
  }

  const runPython = async () => {
    setBusy(true)
    try {
      const res = await runMutation('/api/server/eval', { 
        method: 'POST',
        body: JSON.stringify({ code })
      }, "Code executed")
      setResponse(JSON.stringify(res, null, 2))
    } catch (e: any) {
      setResponse(`Error: ${e.message}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Server Diagnostics</h1>
        <p className="text-muted-foreground">Advanced maintenance and debug tools.</p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><ShieldAlert className="w-5 h-5 text-destructive" /> Danger Zone</CardTitle>
            <CardDescription>Actions here can disrupt gameplay.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Button variant="outline" className="w-full justify-start gap-2" onClick={() => runMaintenance('reload_config')} disabled={busy}>
              <FileJson className="w-4 h-4" /> Reload Master Data
            </Button>
            <Button variant="outline" className="w-full justify-start gap-2" onClick={() => runMaintenance('dump_db')} disabled={busy}>
              <Database className="w-4 h-4" /> Force Database Flush
            </Button>
            <Button variant="outline" className="w-full justify-start gap-2 text-destructive hover:bg-destructive/10" onClick={() => runMaintenance('clear_cache')} disabled={busy}>
              <ShieldAlert className="w-4 h-4" /> Clear All Caches
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Terminal className="w-5 h-5" /> REPL Access</CardTitle>
            <CardDescription>Evaluate Python code on the server.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Textarea 
              className="font-mono text-sm h-[150px] bg-[#09090b] text-[#fafafa] border-border" 
              placeholder="print('Hello from server')"
              value={code}
              onChange={e => setCode(e.target.value)}
            />
            <Button className="w-full gap-2" onClick={runPython} disabled={busy || !code}>
              <Terminal className="w-4 h-4" /> Execute
            </Button>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Execution Output</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="bg-[#09090b] text-[#fafafa] p-4 rounded-md font-mono text-xs overflow-auto min-h-[100px] max-h-[300px]">
            {response || "No output yet."}
          </pre>
        </CardContent>
      </Card>
    </div>
  )
}
