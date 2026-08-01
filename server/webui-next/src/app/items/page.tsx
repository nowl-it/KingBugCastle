"use client"

import { useState, useMemo } from "react"
import { useInventory, useCatalog, runMutation } from "@/lib/api"
import { PlayerBar, usePlayerSelection } from "@/components/player-context"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Plus, Trash2, Search, Gift, KeyRound, Ticket, ScrollText, TrendingUp, Zap, Package, Sparkles, Boxes } from "lucide-react"

const SUB_STYLE: Record<string, { icon: any; cls: string }> = {
  "RewardBoxInventory": { icon: Gift, cls: "bg-amber-500/15 text-amber-400" },
  "InstantRewardBox": { icon: Gift, cls: "bg-amber-500/15 text-amber-400" },
  "Key": { icon: KeyRound, cls: "bg-yellow-500/15 text-yellow-400" },
  "CardLevelUpItem": { icon: Sparkles, cls: "bg-violet-500/15 text-violet-400" },
  "UnitSoul": { icon: Boxes, cls: "bg-rose-500/15 text-rose-400" },
  "Ticket": { icon: Ticket, cls: "bg-sky-500/15 text-sky-400" },
  "Pass": { icon: ScrollText, cls: "bg-cyan-500/15 text-cyan-400" },
  "Exp": { icon: TrendingUp, cls: "bg-emerald-500/15 text-emerald-400" },
  "Instant": { icon: Zap, cls: "bg-orange-500/15 text-orange-400" },
}

function subStyle(sub: string) {
  const key = Object.keys(SUB_STYLE).find(k => (sub || "").toLowerCase().includes(k.toLowerCase()))
  return (key && SUB_STYLE[key]) || { icon: Package, cls: "bg-muted text-muted-foreground" }
}

function ItemIcon({ sub, id, size = "h-10 w-10" }: { sub: string; id?: number; size?: string }) {
  const style = subStyle(sub)
  const Icon = style.icon
  const [broken, setBroken] = useState(false)
  if (id && !broken) {
    return (
      <img
        src={`/assets/items/${id}.webp`}
        alt={String(id)}
        onError={() => setBroken(true)}
        className={`${size} shrink-0 rounded-lg border border-border bg-muted object-cover`}
      />
    )
  }
  return (
    <div className={`flex ${size} shrink-0 items-center justify-center rounded-lg ${style.cls}`}>
      <Icon className="h-5 w-5" />
    </div>
  )
}

export default function ItemsPage() {
  const { selectedId } = usePlayerSelection()
  const { data: inv, mutate } = useInventory(selectedId || undefined)
  const { data: catData } = useCatalog()
  const [q, setQ] = useState("")
  const [addId, setAddId] = useState("")
  const [addCount, setAddCount] = useState("1")

  const items = useMemo(() => (catData?.catalog?.Item || []), [catData])
  const matched = useMemo(() => {
    const query = q.trim().toLowerCase()
    const list = query
      ? items.filter((i: any) => String(i.id).includes(query) || (i.name || "").toLowerCase().includes(query))
      : items
    return list.slice(0, 30)
  }, [items, q])

  const addItem = async () => {
    const id = Number(addId)
    const count = Number(addCount)
    if (!id || !count) return
    await runMutation(`/api/player/${encodeURIComponent(selectedId!)}/inventory`, {
      method: "POST",
      body: JSON.stringify({ id, count }),
    }, `Item ${id} x${count} set`)
    setAddId(""); setAddCount("1")
    mutate()
  }

  const removeItem = async (id: number) => {
    await runMutation(`/api/player/${encodeURIComponent(selectedId!)}/inventory`, {
      method: "POST",
      body: JSON.stringify({ id, count: 0 }),
    }, `Item ${id} removed`)
    mutate()
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Items</h1>
        <p className="text-muted-foreground">Inventory is set by exact count — 0 removes the row. All 173 inventory items available.</p>
      </div>
      <PlayerBar />
      {!selectedId && <Card><CardContent className="py-16 text-center text-muted-foreground">Select a player above.</CardContent></Card>}
      {selectedId && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2"><Boxes className="h-4 w-4" /> Inventory ({inv?.length ?? 0})</CardTitle>
              <CardDescription>Counts are read-only here — set or remove from the catalog panel.</CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              {!inv?.length ? <p className="px-4 py-8 text-sm text-muted-foreground">Inventory is empty.</p> : (
                <Table className="min-w-[440px]">
                  <TableHeader>
                    <TableRow><TableHead>Item</TableHead><TableHead>Sub</TableHead><TableHead className="w-20 text-right">Count</TableHead><TableHead className="w-16" /></TableRow>
                  </TableHeader>
                  <TableBody>
                    {inv.map((it: any) => (
                      <TableRow key={it.id}>
                        <TableCell>
                          <div className="flex items-center gap-3">
                            <ItemIcon sub={it.sub} id={it.id} size="h-9 w-9" />
                            <div>
                              <div className="font-medium">{it.name}</div>
                              <div className="text-xs text-muted-foreground font-mono">#{it.id}</div>
                            </div>
                          </div>
                        </TableCell>
                        <TableCell><span className="text-xs text-muted-foreground">{it.sub}</span></TableCell>
                        <TableCell className="text-right font-mono text-lg">{it.count}</TableCell>
                        <TableCell className="text-right">
                          <Button variant="ghost" size="sm" className="text-destructive" onClick={() => removeItem(it.id)}><Trash2 className="h-3.5 w-3.5" /></Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Add item</CardTitle>
              <CardDescription>Type id or name to search the catalog, then set a count.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="relative mb-3">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input placeholder="Search 173 items..." value={q} onChange={(e) => setQ(e.target.value)} className="pl-8" />
              </div>
              <div className="max-h-[320px] overflow-y-auto border rounded-md divide-y divide-border">
                {matched.map((i: any) => (
                  <button key={i.id} onClick={() => setAddId(String(i.id))} className={`w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-muted/50 ${addId === String(i.id) ? "bg-muted/70" : ""}`}>
                    <ItemIcon sub={i.sub} id={i.id} size="h-9 w-9" />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{i.name}</div>
                      <div className="text-xs text-muted-foreground font-mono">#{i.id} · {i.sub}</div>
                    </div>
                    {addId === String(i.id) && <Sparkles className="h-4 w-4 text-primary" />}
                  </button>
                ))}
                {!matched.length && <p className="px-3 py-6 text-sm text-muted-foreground">No match.</p>}
              </div>
              <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-end">
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">Item ID</label>
                  <Input type="number" className="w-full font-mono sm:w-32" value={addId} onChange={(e) => setAddId(e.target.value)} placeholder="e.g. 380" />
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">Count</label>
                  <Input type="number" className="w-full font-mono sm:w-28" value={addCount} onChange={(e) => setAddCount(e.target.value)} />
                </div>
                <Button onClick={addItem} disabled={!addId || !addCount}><Plus className="h-4 w-4 mr-1" /> Set</Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
