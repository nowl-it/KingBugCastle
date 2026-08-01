"use client"

import { useState, useEffect, useRef } from "react"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Play, Square, Activity } from "lucide-react"

export default function TrackerPage() {
  const [messages, setMessages] = useState<any[]>([])
  const [connected, setConnected] = useState(false)
  const [tracking, setTracking] = useState(true)
  const wsRef = useRef<WebSocket | null>(null)
  const maxMessages = 100

  useEffect(() => {
    let url = (window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.host + '/ws'
    // For local dev where Next.js runs on 3000, force 8081
    if (window.location.port === '3000') {
      url = 'ws://127.0.0.1:8081/ws'
    }

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => setConnected(true)
    ws.onclose = () => setConnected(false)
    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        setMessages(prev => {
          if (!tracking) return prev
          const next = [msg, ...prev]
          if (next.length > maxMessages) return next.slice(0, maxMessages)
          return next
        })
      } catch (e) {
        console.error("WS Parse error", e)
      }
    }

    return () => {
      ws.close()
    }
  }, [tracking])

  const formatPayload = (payload: any) => {
    if (typeof payload === 'string') return payload
    return JSON.stringify(payload, null, 2)
  }

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)]">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Battle Tracker</h1>
          <p className="text-muted-foreground">Live telemetry stream from adb logcat.</p>
        </div>
        <div className="flex items-center gap-4">
          <Badge variant={connected ? "default" : "destructive"} className={connected ? "bg-green-500 hover:bg-green-600" : ""}>
            {connected ? "WebSocket Connected" : "WebSocket Disconnected"}
          </Badge>
          <button 
            onClick={() => setTracking(!tracking)}
            className={`flex items-center gap-2 px-4 py-2 rounded-md font-medium text-sm transition-colors ${
              tracking ? 'bg-amber-500/20 text-amber-500 hover:bg-amber-500/30' : 'bg-green-500/20 text-green-500 hover:bg-green-500/30'
            }`}
          >
            {tracking ? <><Square className="w-4 h-4" /> Pause Stream</> : <><Play className="w-4 h-4" /> Resume Stream</>}
          </button>
        </div>
      </div>

      <Card className="flex-1 overflow-hidden flex flex-col shadow-sm border-border">
        <CardHeader className="border-b bg-muted/20 py-3 px-4">
          <CardTitle className="text-sm font-mono flex items-center gap-2">
            <Activity className="w-4 h-4" /> Live Events ({messages.length})
          </CardTitle>
        </CardHeader>
        <CardContent className="flex-1 overflow-auto p-0 bg-[#09090b] text-[#fafafa] font-mono text-xs">
          {messages.length === 0 ? (
            <div className="flex h-full items-center justify-center text-muted-foreground">
              Waiting for telemetry events... Make sure the game is running on device.
            </div>
          ) : (
            <div className="divide-y divide-white/10">
              {messages.map((m, i) => (
                <div key={i} className="p-4 hover:bg-white/5 transition-colors">
                  <div className="flex items-center gap-4 mb-2">
                    <span className="text-blue-400 font-bold">[{m.type}]</span>
                    <span className="text-white/40">{m.ts}</span>
                  </div>
                  <pre className="whitespace-pre-wrap break-words text-white/80">
                    {formatPayload(m.payload)}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
