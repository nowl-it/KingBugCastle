"use client"

import { useState, useMemo } from "react"
import { useInventory, useCatalog, runMutation } from "@/lib/api"
import { PlayerBar, usePlayerSelection } from "@/components/player-context"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Plus, Trash2, Search } from "lucide-react"

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
        <h1 className="text-3xl font-bold tracking-tight">Items</h1>
        <p className="text-muted-foreground">Inventory is set by exact count — 0 removes the row. All 173 inventory items available.</p>
      </div>
      <PlayerBar />
      {!selectedId && <Card><CardContent className="py-16 text-center text-muted-foreground">Select a player above.</CardContent></Card>}
      {selectedId && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Inventory ({inv?.length ?? 0})</CardTitle>
              <CardDescription>Set count to change quantity; 0 removes.</CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              {!inv?.length ? <p className="px-4 py-8 text-sm text-muted-foreground">Inventory is empty.</p> : (
                <Table>
                  <TableHeader>
                    <TableRow><TableHead>Item</TableHead><TableHead>Sub</TableHead><TableHead className="w-20 text-right">Count</TableHead><TableHead className="w-16" /></TableRow>
                  </TableHeader>
                  <TableBody>
                    {inv.map((it: any) => (
                      <TableRow key={it.id}>
                        <TableCell>
                          <div className="font-medium">{it.name}</div>
                          <div className="text-xs text-muted-foreground font-mono">#{it.id}</div>
                        </TableCell>
                        <TableCell><span className="text-xs text-muted-foreground">{it.sub}</span></TableCell>
                        <TableCell className="text-right font-mono">{it.count}</TableCell>
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
                  <button key={i.id} onClick={() => setAddId(String(i.id))} className={`w-full flex items-center justify-between px-3 py-2 text-left hover:bg-muted/50 ${addId === String(i.id) ? "bg-muted/70" : ""}`}>
                    <div>
                      <div className="text-sm font-medium">{i.name}</div>
                      <div className="text-xs text-muted-foreground font-mono">#{i.id} · {i.sub}</div>
                    </div>
                    {addId === String(i.id) && <Badge variant="secondary">picked</Badge>}
                  </button>
                ))}
                {!matched.length && <p className="px-3 py-6 text-sm text-muted-foreground">No match.</p>}
              </div>
              <div className="mt-3 flex items-end gap-2">
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">Item ID</label>
                  <Input type="number" className="w-32 font-mono" value={addId} onChange={(e) => setAddId(e.target.value)} placeholder="e.g. 380" />
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">Count</label>
                  <Input type="number" className="w-28 font-mono" value={addCount} onChange={(e) => setAddCount(e.target.value)} />
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
