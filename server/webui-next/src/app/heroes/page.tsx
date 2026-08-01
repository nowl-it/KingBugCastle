"use client"

import { useState } from "react"
import { useHeroes, runMutation } from "@/lib/api"
import { PlayerBar, usePlayerSelection } from "@/components/player-context"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Check, Plus, Trash2, Sparkles, Save } from "lucide-react"

const ROLE_BADGE: Record<string, string> = {
  "Warrior": "bg-orange-500/15 text-orange-400 border-orange-500/30",
  "Archer": "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  "Mage": "bg-blue-500/15 text-blue-400 border-blue-500/30",
  "Priest": "bg-cyan-500/15 text-cyan-400 border-cyan-500/30",
  "Assassin": "bg-purple-500/15 text-purple-400 border-purple-500/30",
}

export default function HeroesPage() {
  const { selectedId } = usePlayerSelection()
  const { data, mutate } = useHeroes(selectedId || undefined)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Heroes</h1>
        <p className="text-muted-foreground">Edit levels, souls and awakening tiers of owned heroes; grant missing ones.</p>
      </div>
      <PlayerBar />
      {!selectedId && <Card><CardContent className="py-16 text-center text-muted-foreground">Select a player above.</CardContent></Card>}
      {selectedId && data && (
        <>
          <OwnedTable data={data} onMutate={mutate} />
          <MissingTable data={data} onMutate={mutate} />
        </>
      )}
    </div>
  )
}

function OwnedTable({ data, onMutate }: { data: any; onMutate: () => void }) {
  const { selectedId } = usePlayerSelection()
  const [drafts, setDrafts] = useState<Record<string, Record<string, string>>>({})

  const setField = (unitId: number, key: string, value: string) =>
    setDrafts(prev => ({ ...prev, [unitId]: { ...(prev[unitId] || {}), [key]: value } }))

  const save = async (hero: any) => {
    const draft = drafts[hero.unitId] || {}
    const patch: Record<string, number> = {}
    for (const [k, v] of Object.entries(draft)) {
      const n = Number(v)
      if (!Number.isNaN(n) && n !== hero[k]) patch[k] = n
    }
    if (!Object.keys(patch).length) return
    await runMutation(`/api/player/${encodeURIComponent(selectedId!)}/heroes/${hero.unitId}`, { method: "PATCH", body: JSON.stringify(patch) }, `Hero ${hero.unitId} updated`)
    onMutate()
  }

  const remove = async (hero: any) => {
    if (!window.confirm(`Remove hero ${hero.unitId} (${hero.name})?`)) return
    await runMutation(`/api/player/${encodeURIComponent(selectedId!)}/heroes/${hero.unitId}`, { method: "DELETE" }, "Hero removed")
    onMutate()
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Owned ({data.owned.length})</CardTitle>
        <CardDescription>Inline edits apply immediately via PATCH.</CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Hero</TableHead>
              <TableHead>Role</TableHead>
              <TableHead className="w-24">Level</TableHead>
              <TableHead className="w-24">Exp</TableHead>
              <TableHead className="w-24">Soul</TableHead>
              <TableHead className="w-24">Awaken</TableHead>
              <TableHead className="w-24">Skins</TableHead>
              <TableHead className="w-40 text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.owned.map((h: any) => {
              const d = drafts[h.unitId] || {}
              return (
                <TableRow key={h.unitId}>
                  <TableCell>
                    <div className="font-medium">{h.name}</div>
                    <div className="text-xs text-muted-foreground font-mono">#{h.unitId}</div>
                  </TableCell>
                  <TableCell>
                    <Badge className={ROLE_BADGE[h.role] || ""} variant="outline">{h.role}</Badge>
                  </TableCell>
                  <TableCell><Input type="number" className="h-8 w-20 font-mono" value={d.level ?? h.level} onChange={(e) => setField(h.unitId, "level", e.target.value)} /></TableCell>
                  <TableCell><Input type="number" className="h-8 w-20 font-mono" value={d.exp ?? h.exp} onChange={(e) => setField(h.unitId, "exp", e.target.value)} /></TableCell>
                  <TableCell><Input type="number" className="h-8 w-20 font-mono" value={d.soul ?? h.soul} onChange={(e) => setField(h.unitId, "soul", e.target.value)} /></TableCell>
                  <TableCell><Input type="number" className="h-8 w-20 font-mono" value={d.potentialTier ?? h.potentialTier} onChange={(e) => setField(h.unitId, "potentialTier", e.target.value)} /></TableCell>
                  <TableCell className="text-sm text-muted-foreground">{h.skins}</TableCell>
                  <TableCell className="text-right">
                    <Button variant="ghost" size="sm" onClick={() => save(h)}><Save className="h-3.5 w-3.5" /></Button>
                    <Button variant="ghost" size="sm" className="text-destructive" onClick={() => remove(h)}><Trash2 className="h-3.5 w-3.5" /></Button>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function MissingTable({ data, onMutate }: { data: any; onMutate: () => void }) {
  const { selectedId } = usePlayerSelection()
  const [level, setLevel] = useState("30")
  const [soul, setSoul] = useState("999")

  const grant = async (h: any) => {
    await runMutation(`/api/player/${encodeURIComponent(selectedId!)}/heroes/${h.unitId}`, { method: "POST" }, `${h.name} granted`)
    onMutate()
  }

  const grantAll = async () => {
    await runMutation(`/api/player/${encodeURIComponent(selectedId!)}/heroes-grant-all`, {
      method: "POST",
      body: JSON.stringify({ level: Number(level), soul: Number(soul) }),
    }, "All missing heroes granted")
    onMutate()
  }

  if (!data.missing.length) return (
    <Card><CardContent className="py-6 flex items-center gap-2 text-muted-foreground"><Check className="h-4 w-4" /> Every hero in master data is owned.</CardContent></Card>
  )

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-base">Missing ({data.missing.length})</CardTitle>
            <CardDescription>Heroes in master data this player does not own yet.</CardDescription>
          </div>
          <div className="flex items-end gap-2">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Level</label>
              <Input type="number" className="h-8 w-20 font-mono" value={level} onChange={(e) => setLevel(e.target.value)} />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Soul</label>
              <Input type="number" className="h-8 w-20 font-mono" value={soul} onChange={(e) => setSoul(e.target.value)} />
            </div>
            <Button size="sm" onClick={grantAll}><Sparkles className="h-3.5 w-3.5 mr-1" /> Grant all</Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow><TableHead>Hero</TableHead><TableHead>Role</TableHead><TableHead className="w-24 text-right">Action</TableHead></TableRow>
          </TableHeader>
          <TableBody>
            {data.missing.map((h: any) => (
              <TableRow key={h.unitId}>
                <TableCell>
                  <div className="font-medium">{h.name}</div>
                  <div className="text-xs text-muted-foreground font-mono">#{h.unitId}</div>
                </TableCell>
                <TableCell><Badge className={ROLE_BADGE[h.role] || ""} variant="outline">{h.role}</Badge></TableCell>
                <TableCell className="text-right">
                  <Button variant="outline" size="sm" onClick={() => grant(h)}><Plus className="h-3.5 w-3.5 mr-1" /> Grant</Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
