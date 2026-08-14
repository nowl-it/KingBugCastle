"use client"

import { useState, useEffect, useMemo } from "react"
import { usePlayers, usePlayer, usePlayerRaw, runMutation } from "@/lib/api"
import { usePlayerSelection } from "@/components/player-context"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Search, Plus, Copy, Trash2, Save, RefreshCw, Crown, Zap } from "lucide-react"

const EDITABLE_FIELDS: Record<string, { label: string; type?: string }> = {
  name: { label: "Name" },
  castleName: { label: "Castle name" },
  gold: { label: "Gold", type: "number" },
  cash: { label: "Cash", type: "number" },
  heart: { label: "Heart", type: "number" },
  level: { label: "Account level", type: "number" },
  exp: { label: "Exp", type: "number" },
  bestClearedStage: { label: "Best stage", type: "number" },
  bestClearedTheme: { label: "Best theme", type: "number" },
  bestClearedHardStage: { label: "Best hard stage", type: "number" },
  bestClearedHardTheme: { label: "Best hard theme", type: "number" },
  buildingPoints: { label: "Building points", type: "number" },
  playedCount: { label: "Battles played", type: "number" },
  winCount: { label: "Battles won", type: "number" },
}

export default function PlayersPage() {
  const { data: players, mutate: mutatePlayers } = usePlayers()
  const { selectedId, setSelectedId } = usePlayerSelection()
  const [query, setQuery] = useState("")
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState("")
  const [newUid, setNewUid] = useState("")

  const list = useMemo(() => {
    const arr = Array.isArray(players) ? players : []
    const q = query.trim().toLowerCase()
    if (!q) return arr
    return arr.filter((p: any) =>
      (p.name || "").toLowerCase().includes(q) ||
      (p.id || "").toLowerCase().includes(q) ||
      (p.uid || "").toLowerCase().includes(q))
  }, [players, query])

  const handleCreate = async () => {
    if (!newName.trim()) return
    await runMutation("/api/players", {
      method: "POST",
      body: JSON.stringify({ name: newName, uid: newUid.trim() || undefined }),
    }, "Player created")
    setNewName(""); setNewUid(""); setShowCreate(false)
    mutatePlayers()
  }

  const handleClone = async (pid: string) => {
    await runMutation(`/api/players/${encodeURIComponent(pid)}/clone`, { method: "POST" }, "Player cloned")
    mutatePlayers()
  }

  const handleDelete = async (pid: string) => {
    if (!window.confirm(`Delete player ${pid}? This is irreversible.`)) return
    await runMutation(`/api/players/${encodeURIComponent(pid)}`, { method: "DELETE" }, "Player deleted")
    if (selectedId === pid) setSelectedId(null)
    mutatePlayers()
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Players</h1>
          <p className="text-muted-foreground">Manage saves, edit currency and raw state.</p>
        </div>
        <div className="flex flex-col gap-2 sm:w-auto sm:flex-row sm:items-center">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input placeholder="Search name / id..." value={query} onChange={(e) => setQuery(e.target.value)} className="w-full pl-8 sm:w-64" />
          </div>
          <Button onClick={() => setShowCreate(v => !v)} className="w-full sm:w-auto"><Plus className="h-4 w-4 mr-1" /> New player</Button>
        </div>
      </div>

      {showCreate && (
        <Card>
          <CardHeader><CardTitle>Create player</CardTitle><CardDescription>Built by the game server (default save + content-version expansion).</CardDescription></CardHeader>
          <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1 space-y-1">
              <label className="text-xs text-muted-foreground">Name</label>
              <Input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="e.g. Newbie" />
            </div>
            <div className="flex-1 space-y-1">
              <label className="text-xs text-muted-foreground">UID (optional, auto-generated)</label>
              <Input value={newUid} onChange={(e) => setNewUid(e.target.value)} placeholder="player-xxxx" className="font-mono" />
            </div>
            <Button onClick={handleCreate} disabled={!newName.trim()}>Create</Button>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(320px,380px)_1fr]">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">{list.length} player{list.length === 1 ? "" : "s"}</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <ul className="max-h-[65vh] overflow-y-auto divide-y divide-border">
              {list.map((p: any) => (
                <li key={p.id}>
                  <button
                    onClick={() => setSelectedId(p.id)}
                    className={`w-full flex items-center justify-between gap-2 px-4 py-3 text-left hover:bg-muted/50 transition-colors ${selectedId === p.id ? "bg-muted/70" : ""}`}
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={`h-2 w-2 rounded-full shrink-0 ${p.active ? "bg-green-500" : "bg-muted-foreground/40"}`} />
                        <span className="text-sm font-medium truncate">{p.name}</span>
                        {p.active && <Badge variant="secondary" className="text-[10px] px-1.5">ACTIVE</Badge>}
                      </div>
                      <div className="text-xs text-muted-foreground font-mono truncate">{p.id}</div>
                    </div>
                    <div className="text-right shrink-0">
                      <div className="text-sm">lv {p.level}</div>
                      <div className="text-xs text-muted-foreground">{p.counts?.cards ?? 0} heroes</div>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        {selectedId ? <PlayerDetail pid={selectedId} onMutate={mutatePlayers} onClone={handleClone} onDelete={handleDelete} /> : (
          <Card>
            <CardContent className="py-16 text-center text-muted-foreground">
              Select a player to view or edit their save.
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}

function PlayerDetail({ pid, onMutate, onClone, onDelete }: {
  pid: string
  onMutate: () => void
  onClone: (pid: string) => void
  onDelete: (pid: string) => void
}) {
  const { data: detail } = usePlayer(pid)
  const { data: raw } = usePlayerRaw(pid)
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [rawDraft, setRawDraft] = useState<string>("")
  const [rawError, setRawError] = useState<string | null>(null)

  const sum = detail?.summary

  useEffect(() => {
    if (sum) {
      const next: Record<string, string> = {}
      for (const k of Object.keys(EDITABLE_FIELDS)) {
        next[k] = sum[k] !== undefined && sum[k] !== null ? String(sum[k]) : ""
      }
      setEdits(next)
    }
  }, [pid, sum?.name, sum?.gold, sum?.cash, sum?.level])

  useEffect(() => {
    if (raw) setRawDraft(JSON.stringify(raw, null, 2))
  }, [pid, raw])

  const saveEdits = async () => {
    const patch: Record<string, any> = {}
    for (const [k, v] of Object.entries(edits)) {
      const spec = EDITABLE_FIELDS[k]
      if (spec?.type === "number") {
        const n = Number(v)
        if (!Number.isNaN(n) && n !== sum?.[k]) patch[k] = n
      } else if (v !== sum?.[k]) {
        patch[k] = v
      }
    }
    if (!Object.keys(patch).length) return
    await runMutation(`/api/player/${encodeURIComponent(pid)}`, { method: "PATCH", body: JSON.stringify(patch) }, "Save updated")
    onMutate()
  }

  const saveRaw = async () => {
    setRawError(null)
    let parsed: any
    try {
      parsed = JSON.parse(rawDraft)
    } catch (e: any) {
      setRawError("Invalid JSON: " + e.message)
      return
    }
    await runMutation(`/api/player/${encodeURIComponent(pid)}/raw`, { method: "PUT", body: JSON.stringify(parsed) }, "Raw state replaced")
    onMutate()
  }

  const handleMacro = async (macroId: string) => {
    if (!window.confirm(`Apply macro '${macroId}'? This will overwrite relevant fields.`)) return
    await runMutation(`/api/player/${encodeURIComponent(pid)}/macro`, { method: "POST", body: JSON.stringify({ macro: macroId }) }, "Macro applied successfully")
    onMutate()
  }

  if (!detail || !sum) return <Card><CardContent className="py-16 text-center text-muted-foreground">Loading player...</CardContent></Card>

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2">
                {sum.name} {sum.active && <Badge variant="secondary">ACTIVE</Badge>}
              </CardTitle>
              <CardDescription className="break-all font-mono">{pid} · uid {sum.uid} · castle “{sum.castleName || "—"}”</CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="outline" size="sm" onClick={() => onClone(pid)}><Copy className="h-3.5 w-3.5 mr-1" /> Clone</Button>
              <Button variant="destructive" size="sm" onClick={() => onDelete(pid)}><Trash2 className="h-3.5 w-3.5 mr-1" /> Delete</Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {Object.entries(EDITABLE_FIELDS).map(([k, spec]) => (
              <div key={k} className="space-y-1">
                <label className="text-xs text-muted-foreground">{spec.label}</label>
                <Input
                  type={spec.type || "text"}
                  value={edits[k] ?? ""}
                  onChange={(e) => setEdits(prev => ({ ...prev, [k]: e.target.value }))}
                />
              </div>
            ))}
          </div>
          <Button className="mt-4" onClick={saveEdits}><Save className="h-4 w-4 mr-1" /> Save fields</Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Zap className="h-4 w-4" /> Macro Profiles</CardTitle>
          <CardDescription>Quickly grant bundles of items and resources without editing individual fields.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-4">
            <div>
              <h4 className="text-sm font-medium mb-2">Resources & Inventory</h4>
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" onClick={() => handleMacro("max_resources")}>Max Resources (290909)</Button>
                <Button variant="secondary" onClick={() => handleMacro("max_wealth")}>Max Wealth (Gold, Cash, Tokens)</Button>
                <Button variant="secondary" onClick={() => handleMacro("max_inventory")}>Max All Inventory Items</Button>
              </div>
            </div>
            <div>
              <h4 className="text-sm font-medium mb-2">Heroes</h4>
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" onClick={() => handleMacro("hero_basic")}>Basic Heroes (Lv.20)</Button>
                <Button variant="secondary" onClick={() => handleMacro("hero_advanced")}>Advanced Heroes (Lv.30)</Button>
                <Button variant="secondary" onClick={() => handleMacro("hero_max")}>Max Heroes (+ Unreleased)</Button>
                <Button variant="secondary" onClick={() => handleMacro("max_heroes")}>Max All Heroes (Old)</Button>
              </div>
            </div>
            <div>
              <h4 className="text-sm font-medium mb-2">Legacies & Accessories</h4>
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" onClick={() => handleMacro("legacy_basic")}>Basic Legacies (0*)</Button>
                <Button variant="secondary" onClick={() => handleMacro("legacy_advanced")}>Advanced Legacies (10*)</Button>
                <Button variant="secondary" onClick={() => handleMacro("legacy_max")}>Max Legacies (+ Unreleased)</Button>
                <Button variant="secondary" onClick={() => handleMacro("accessory_admin")}>Admin Accessories</Button>
              </div>
            </div>
            <div>
              <h4 className="text-sm font-medium mb-2">Rift Weapons & Crystals</h4>
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" onClick={() => handleMacro("rift_legendary_all")}>✨ Grant 216 Legendary Crystals (Selected Player)</Button>
                <Button variant="outline" onClick={async () => {
                  if (!window.confirm("Grant 216 Legendary Rift Crystals and clean test equipment for ALL players on the server?")) return
                  await runMutation("/api/players/grant-all-legendary-rift-crystals", { method: "POST" }, "Granted 216 crystals to all players")
                  onMutate()
                }}>⚡ Grant 216 Crystals to ALL Players</Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2"><Crown className="h-4 w-4" /> Raw state (JSON)</CardTitle>
              <CardDescription>Full save as the game server reads it. uid is forced back to the row key on save.</CardDescription>
            </div>
            <Button variant="outline" size="sm" onClick={() => setRawDraft(JSON.stringify(raw, null, 2))}><RefreshCw className="h-3.5 w-3.5 mr-1" /> Reload</Button>
          </div>
        </CardHeader>
        <CardContent>
          <textarea
            value={rawDraft}
            onChange={(e) => setRawDraft(e.target.value)}
            spellCheck={false}
            className="w-full h-96 rounded-md border border-input bg-background p-3 font-mono text-xs focus:outline-none focus:ring-2 focus:ring-ring"
          />
          {rawError && <p className="mt-2 text-sm text-destructive">{rawError}</p>}
          <Button className="mt-3" onClick={saveRaw}><Save className="h-4 w-4 mr-1" /> Replace raw state</Button>
        </CardContent>
      </Card>
    </div>
  )
}
