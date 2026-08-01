"use client"

import { useState, useMemo } from "react"
import { useCatalog, usePlayer, runMutation } from "@/lib/api"
import { PlayerBar, usePlayerSelection } from "@/components/player-context"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Mail, Send, Trash2, Search } from "lucide-react"

export default function MailPage() {
  const { data: catData } = useCatalog()
  const { selectedId } = usePlayerSelection()
  const { data: detail, mutate: mutateDetail } = usePlayer(selectedId || undefined)

  const grantable = catData?.grantable || []
  const catalog = catData?.catalog || {}

  const [title, setTitle] = useState("")
  const [text, setText] = useState("")
  const [rewardType, setRewardType] = useState("Gold")
  const [rewardId, setRewardId] = useState("")
  const [rewardAmount, setRewardAmount] = useState("1")
  const [days, setDays] = useState("30")
  const [pickedId, setPickedId] = useState("")
  const [q, setQ] = useState("")

  const rewardList = useMemo(() => catalog[rewardType] || [], [catalog, rewardType])
  const matched = useMemo(() => {
    const query = q.trim().toLowerCase()
    const list = query
      ? rewardList.filter((r: any) => String(r.id).includes(query) || (r.name || "").toLowerCase().includes(query))
      : rewardList
    return list.slice(0, 20)
  }, [rewardList, q])

  const needsId = rewardType !== "Gold" && rewardType !== "Cash" && rewardType !== "Heart"

  const payload = () => ({
    title,
    text,
    rewardType,
    rewardId: needsId ? Number(rewardId || 0) : 0,
    rewardAmount: Number(rewardAmount || 0),
    days: Number(days || 30),
  })

  const broadcast = async () => {
    await runMutation("/api/mail/broadcast", { method: "POST", body: JSON.stringify(payload()) }, "Mail broadcast to all players")
  }

  const sendTargeted = async () => {
    await runMutation(`/api/player/${encodeURIComponent(selectedId!)}/mail`, { method: "POST", body: JSON.stringify(payload()) }, "Mail sent")
    mutateDetail()
  }

  const removePost = async (postId: number) => {
    await runMutation(`/api/player/${encodeURIComponent(selectedId!)}/mail/${postId}`, { method: "DELETE" }, "Mail deleted")
    mutateDetail()
  }

  const posts = detail?.posts || []

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Mail</h1>
        <p className="text-muted-foreground">Plain title/body are localization keys; prefix with <code className="text-xs bg-muted px-1 rounded">@raw:</code> to send literal text.</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="text-base">Compose</CardTitle><CardDescription>Reward types and ids follow the client vocabulary (Key → ShopItem id, Item → InventoryItems id).</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            <Input placeholder="Title (localization key or @raw: literal)" value={title} onChange={(e) => setTitle(e.target.value)} />
            <Textarea placeholder="Body (localization key or @raw: literal)" value={text} onChange={(e) => setText(e.target.value)} className="min-h-20" />

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
                      {matched.map((r: any) => (
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
              <Input type="number" value={days} onChange={(e) => setDays(e.target.value)} className="font-mono w-32" />
            </div>

            <div className="flex gap-2 pt-2">
              <Button onClick={broadcast} className="flex-1"><Send className="h-4 w-4 mr-1" /> Broadcast to all players</Button>
              {selectedId && <Button variant="outline" onClick={sendTargeted} className="flex-1"><Mail className="h-4 w-4 mr-1" /> Send to {selectedId}</Button>}
            </div>
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
                {posts.map((p: any) => (
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
