"use client"

import { useState, useMemo } from "react"
import { useCatalog, usePlayer, usePlayers, runMutation } from "@/lib/api"
import { usePlayerSelection } from "@/components/player-context"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Mail, Send, Trash2, Search, Users, UserRound } from "lucide-react"

type CatalogReward = { id: number; name: string }
type PlayerSummary = { id: string; name: string }
type Post = { id: number; title?: string; text?: string; rewardType?: string; rewardId?: number; rewardAmount?: number; untilAt: string }

export default function MailPage() {
  const { data: catData, error: catalogError } = useCatalog()
  const { selectedId } = usePlayerSelection()
  const { data: detail, mutate: mutateDetail } = usePlayer(selectedId || undefined)
  const { data: players } = usePlayers()

  const grantable = (catData?.grantable || []) as string[]
  const catalog = catData?.catalog as Record<string, CatalogReward[]> | undefined

  // Recipient mode: "all" (broadcast) or "pick" (one or more players)
  const [mode, setMode] = useState<"all" | "pick">("all")
  const [picked, setPicked] = useState<Set<string>>(new Set())

  const [title, setTitle] = useState("")
  const [text, setText] = useState("")
  const [rewardType, setRewardType] = useState("Gold")
  const [rewardId, setRewardId] = useState("")
  const [rewardAmount, setRewardAmount] = useState("1")
  const [days, setDays] = useState("30")
  const [pickedId, setPickedId] = useState("")
  const [q, setQ] = useState("")
  const [pq, setPq] = useState("")

  const rewardList = useMemo(() => catalog?.[rewardType] || [], [catalog, rewardType])
  const matched = useMemo(() => {
    const query = q.trim().toLowerCase()
    const list = query
      ? rewardList.filter((r) => String(r.id).includes(query) || (r.name || "").toLowerCase().includes(query))
      : rewardList
    return list.slice(0, 20)
  }, [rewardList, q])

  const playerList = useMemo(() => {
    const arr = (Array.isArray(players) ? players : []) as PlayerSummary[]
    const query = pq.trim().toLowerCase()
    return query
      ? arr.filter((p) => (p.name || "").toLowerCase().includes(query) || (p.id || "").toLowerCase().includes(query))
      : arr
  }, [players, pq])

  const needsId = rewardType !== "Gold" && rewardType !== "Cash" && rewardType !== "Heart"

  const togglePick = (pid: string) => {
    setPicked(prev => {
      const next = new Set(prev)
      if (next.has(pid)) next.delete(pid); else next.add(pid)
      return next
    })
  }

  const payload = () => ({
    title,
    text,
    rewardType,
    rewardId: needsId ? Number(rewardId || 0) : 0,
    rewardAmount: Number(rewardAmount || 0),
    days: Number(days || 30),
  })

  const send = async () => {
    if (!title.trim() && !text.trim()) {
      window.dispatchEvent(new CustomEvent("kgc:toast", { detail: { message: "Title or body required", type: "error" } }))
      return
    }
    if (mode === "all") {
      await runMutation("/api/mail/broadcast", { method: "POST", body: JSON.stringify(payload()) }, "Mail broadcast to all players")
    } else {
      const targets = [...picked]
      if (!targets.length) {
        window.dispatchEvent(new CustomEvent("kgc:toast", { detail: { message: "Pick at least one player", type: "error" } }))
        return
      }
      for (const pid of targets) {
        await runMutation(`/api/player/${encodeURIComponent(pid)}/mail`, { method: "POST", body: JSON.stringify(payload()) })
      }
      window.dispatchEvent(new CustomEvent("kgc:toast", { detail: { message: `Mail sent to ${targets.length} player(s)`, type: "success" } }))
      if (selectedId) mutateDetail()
    }
  }

  const removePost = async (postId: number) => {
    await runMutation(`/api/player/${encodeURIComponent(selectedId!)}/mail/${postId}`, { method: "DELETE" }, "Mail deleted")
    mutateDetail()
  }

  const posts = detail?.posts || []

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Mail</h1>
        <p className="text-muted-foreground">Plain title/body are localization keys; prefix with <code className="text-xs bg-muted px-1 rounded">@raw:</code> to send literal text.</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2"><Mail className="h-4 w-4" /> Compose</CardTitle>
            <CardDescription>Reward types and ids follow the client vocabulary (Key → ShopItem id, Item → InventoryItems id).</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {/* Recipients */}
            <div className="rounded-md border border-border p-3">
              <label className="text-xs font-medium text-muted-foreground">Recipients</label>
              <div className="mt-2 flex gap-4">
                <label className="flex cursor-pointer items-center gap-2 text-sm">
                  <input type="radio" name="recipients" checked={mode === "all"} onChange={() => setMode("all")} className="accent-primary" />
                  <Users className="h-4 w-4 text-muted-foreground" /> All players
                </label>
                <label className="flex cursor-pointer items-center gap-2 text-sm">
                  <input type="radio" name="recipients" checked={mode === "pick"} onChange={() => setMode("pick")} className="accent-primary" />
                  <UserRound className="h-4 w-4 text-muted-foreground" /> Pick players ({picked.size})
                </label>
              </div>
              {mode === "pick" && (
                <div className="mt-3 space-y-2">
                  <div className="relative">
                    <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                    <Input placeholder="Filter players..." value={pq} onChange={(e) => setPq(e.target.value)} className="pl-8 h-9" />
                  </div>
                  <div className="max-h-36 overflow-y-auto rounded-md border border-border divide-y divide-border">
                    {playerList.map((p) => (
                      <label key={p.id} className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm hover:bg-muted/50">
                        <input type="checkbox" checked={picked.has(p.id)} onChange={() => togglePick(p.id)} className="accent-primary" />
                        <span className="min-w-0 flex-1 truncate">{p.name}</span>
                        <span className="text-xs text-muted-foreground font-mono">{p.id}</span>
                      </label>
                    ))}
                    {!playerList.length && <p className="px-3 py-4 text-sm text-muted-foreground">No players.</p>}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {[...picked].map(pid => (
                      <Badge key={pid} variant="secondary" className="gap-1">
                        {pid}
                        <button onClick={() => togglePick(pid)} className="text-muted-foreground hover:text-foreground">×</button>
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <Input placeholder="Title (localization key or @raw: literal)" value={title} onChange={(e) => setTitle(e.target.value)} />
            <Textarea placeholder="Body (localization key or @raw: literal)" value={text} onChange={(e) => setText(e.target.value)} className="min-h-20" />

            {catalogError && (
              <p className="text-xs text-destructive">Reward catalog unavailable ({catalogError.message}) — only Gold/Cash/Heart can be attached right now.</p>
            )}

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Reward type</label>
                <select
                  value={rewardType}
                  onChange={(e) => { setRewardType(e.target.value); setRewardId(""); setQ("") }}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  {grantable.map((t: string) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Amount</label>
                <Input type="number" value={rewardAmount} onChange={(e) => setRewardAmount(e.target.value)} className="font-mono" />
              </div>
            </div>

            {needsId && (
              <>
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">Reward id ({rewardType})</label>
                  <Input type="number" value={rewardId} onChange={(e) => setRewardId(e.target.value)} placeholder="id" className="font-mono" />
                </div>
                {rewardList.length > 0 && (
                  <div>
                    <div className="relative mb-2">
                      <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                      <Input placeholder={`Search ${rewardType} names...`} value={q} onChange={(e) => setQ(e.target.value)} className="pl-8" />
                    </div>
                    <div className="max-h-40 overflow-y-auto border rounded-md divide-y divide-border">
                      {matched.map((r) => (
                        <button key={r.id} onClick={() => { setRewardId(String(r.id)); setPickedId(String(r.id)) }} className={`w-full flex items-center justify-between px-3 py-1.5 text-left hover:bg-muted/50 ${pickedId === String(r.id) ? "bg-muted/70" : ""}`}>
                          <span className="text-sm">{r.name}</span>
                          <span className="text-xs text-muted-foreground font-mono">#{r.id}</span>
                        </button>
                      ))}
                      {!matched.length && <p className="px-3 py-4 text-sm text-muted-foreground">No match.</p>}
                    </div>
                  </div>
                )}
              </>
            )}

            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Expires in (days)</label>
              <Input type="number" value={days} onChange={(e) => setDays(e.target.value)} className="w-full font-mono sm:w-32" />
            </div>

            <Button onClick={send} className="w-full"><Send className="h-4 w-4 mr-1" />
              {mode === "all" ? "Broadcast to all players" : `Send to ${picked.size || "..."} player(s)`}
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Inbox</CardTitle>
            <CardDescription>{selectedId ? `Mail waiting for ${selectedId}: ${posts.length} post(s)` : "Select a player above to see their inbox."}</CardDescription>
          </CardHeader>
          <CardContent className="p-0">
            {!selectedId && <p className="px-4 py-8 text-sm text-muted-foreground">Pick a player in the bar above.</p>}
            {selectedId && !posts.length && <p className="px-4 py-8 text-sm text-muted-foreground">No mail waiting.</p>}
            {selectedId && posts.length > 0 && (
              <ul className="divide-y divide-border max-h-[52vh] overflow-y-auto">
                {(posts as Post[]).map((p) => (
                  <li key={p.id} className="flex items-start justify-between gap-3 px-4 py-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium">{p.title || "(no title)"}</span>
                        {p.rewardType && <Badge variant="outline" className="text-[10px]">{p.rewardType}{p.rewardId ? ` #${p.rewardId}` : ""} ×{p.rewardAmount}</Badge>}
                      </div>
                      {p.text && <p className="text-xs text-muted-foreground truncate mt-0.5">{p.text}</p>}
                      <div className="text-xs text-muted-foreground font-mono mt-1">id {p.id} · until {p.untilAt}</div>
                    </div>
                    <Button variant="ghost" size="sm" className="text-destructive shrink-0" onClick={() => removePost(p.id)}><Trash2 className="h-3.5 w-3.5" /></Button>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
