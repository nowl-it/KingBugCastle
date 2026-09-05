"use client"

import { useMemo, useState } from "react"
import { useAccessories, useCatalog } from "@/lib/api"
import { runMutation } from "@/lib/api"
import { PlayerBar, usePlayerSelection } from "@/components/player-context"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Plus, Trash2, Save, Loader2, Check, Gem, Info } from "lucide-react"
import { useQuery } from "@tanstack/react-query"

function SubStatRows({
  slots, options, rows, onChange,
}: {
  slots: number
  options: string[]
  rows: { key: string; value: string }[]
  onChange: (rows: { key: string; value: string }[]) => void
}) {
  const set = (i: number, patch: Partial<{ key: string; value: string }>) => {
    const next = rows.map((r, j) => (j === i ? { ...r, ...patch } : r))
    onChange(next)
  }
  return (
    <div className="space-y-2">
      {rows.map((r, i) => (
        <div key={i} className="flex items-center gap-2">
          <select
            value={r.key}
            onChange={(e) => set(i, { key: e.target.value })}
            className="h-8 flex-1 rounded-md border border-input bg-background px-2 text-sm"
          >
            {options.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
          <Input
            type="number" step="0.1" min={0} max={26} value={r.value}
            onChange={(e) => set(i, { value: e.target.value })}
            className="h-8 w-24 font-mono"
          />
          {i > 0 && (
            <Button variant="ghost" size="icon" className="h-8 w-8 text-destructive"
              onClick={() => onChange(rows.filter((_, j) => j !== i))}>
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      ))}
    </div>
  )
}

export default function AccessoriesPage() {
  const { selectedId } = usePlayerSelection()
  const { data, mutate: mutateAccs } = useAccessories(selectedId || undefined)
  const { data: catalog } = useCatalog()

  // fetch legal builder options + the persisted custom config
  const { data: opts } = useQuery({
    queryKey: ["/api/admin-accessories/options"],
    queryFn: () => fetch("/api/admin-accessories/options").then(r => r.json()),
  })
  const { data: cfgData, mutate: mutateCfg } = useQuery({
    queryKey: ["/api/admin-accessories"],
    queryFn: () => fetch("/api/admin-accessories").then(r => r.json()),
  })

  const [name, setName] = useState("")
  const [type, setType] = useState("Necklace")
  const [rarity, setRarity] = useState("3")
  const [level, setLevel] = useState("20")
  const [synergy, setSynergy] = useState("0")
  const [mainStat, setMainStat] = useState("AtkPer")
  const [subs, setSubs] = useState<{ key: string; value: string }[]>([{ key: "BaseDefPen", value: "26" }])
  const [saving, setSaving] = useState(false)

  const mainStats: string[] = opts?.mainStatsByType?.[type] || []
  const slots = opts?.slotsByRarity?.[rarity] || 1
  const budget = opts?.budgetByRarity?.[rarity] || 0
  const subKeys: string[] = opts?.subStatKeys || []
  const scoreMax = opts?.scoreMax ?? 26.0

  const shown = useMemo(() => {
    const arr = subs.slice(0, slots)
    while (arr.length < 1) arr.push({ key: subKeys[0] || "AtkPer", value: "0" })
    return arr
  }, [subs, slots, subKeys])

  const subsTotal = shown.reduce((s, r) => s + (parseFloat(r.value) || 0), 0)

  const resetForm = () => {
    setName(""); setType("Necklace"); setRarity("3"); setLevel("20"); setSynergy("0")
    setMainStat(opts?.mainStatsByType?.["Necklace"]?.[0] || "AtkPer")
    setSubs([{ key: subKeys[0] || "AtkPer", value: "26" }])
  }

  const addEntry = async () => {
    if (!name.trim()) { window.dispatchEvent(new CustomEvent("kgc:toast", { detail: { message: "Enter a name", type: "error" } })); return }
    if (subsTotal > budget + 0.001) {
      window.dispatchEvent(new CustomEvent("kgc:toast", { detail: { message: `Sub-stat total ${subsTotal.toFixed(1)} exceeds the ${budget} budget`, type: "error" } })); return
    }
    setSaving(true)
    try {
      await runMutation("/api/admin-accessories", {
        method: "POST",
        body: JSON.stringify({
          name, type, rarity: Number(rarity), level: Number(level),
          synergy: Number(synergy), mainStat,
          subStats: shown.map(r => ({ key: r.key, value: parseFloat(r.value) || 0 })),
        }),
      }, "Accessory added to the admin set (saved)")
      resetForm(); mutateCfg()
    } finally { setSaving(false) }
  }

  const deleteEntry = async (idx: number) => {
    await runMutation("/api/admin-accessories/delete", {
      method: "POST", body: JSON.stringify({ index: idx }),
    }, "Accessory removed")
    mutateCfg()
  }

  const applyToPlayer = async () => {
    if (!selectedId) return
    await runMutation("/api/admin-accessories/apply", { method: "POST", body: JSON.stringify({ pid: selectedId }) }, "Admin set applied to player (replaces)")
    mutateAccs()
  }

  const adminList = cfgData?.accessories || []
  const synNames = new Map((opts?.synergies || []).map((s: any) => [s.id, s.name]))

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Accessories</h1>
        <p className="text-muted-foreground">Build custom accessories (saved to the admin set) and apply them to a player. Applying replaces — the player's accessories become exactly the admin set.</p>
      </div>
      <PlayerBar />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Plus className="h-4 w-4" /> Add Accessories</CardTitle>
          <CardDescription>Built from the game's real rules (rarity slots, shared budget, legal stats). Saved to the admin set.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
            <label className="space-y-1"><span className="text-xs text-muted-foreground">Name</span><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. SS Menace Necklace" /></label>
            <label className="space-y-1"><span className="text-xs text-muted-foreground">Type</span>
              <select value={type} onChange={(e) => { setType(e.target.value); setMainStat(opts?.mainStatsByType?.[e.target.value]?.[0] || "AtkPer") }} className="h-8 w-full rounded-md border border-input bg-background px-2 text-sm">
                {(opts?.types || []).map((t: any) => <option key={t.id} value={t.name}>{t.name}</option>)}
              </select>
            </label>
            <label className="space-y-1"><span className="text-xs text-muted-foreground">Rarity</span>
              <select value={rarity} onChange={(e) => setRarity(e.target.value)} className="h-8 w-full rounded-md border border-input bg-background px-2 text-sm">
                {(opts?.rarities || []).map((r: any) => <option key={r.id} value={String(r.id)}>{r.name}</option>)}
              </select>
            </label>
            <label className="space-y-1"><span className="text-xs text-muted-foreground">Level</span><Input type="number" min={1} max={20} value={level} onChange={(e) => setLevel(e.target.value)} /></label>
            <label className="space-y-1"><span className="text-xs text-muted-foreground">Synergy</span>
              <select value={synergy} onChange={(e) => setSynergy(e.target.value)} className="h-8 w-full rounded-md border border-input bg-background px-2 text-sm">
                {(opts?.synergies || []).map((s: any) => <option key={s.id} value={String(s.id)}>{s.name}</option>)}
              </select>
            </label>
            <label className="space-y-1"><span className="text-xs text-muted-foreground">Main Stat</span>
              <select value={mainStat} onChange={(e) => setMainStat(e.target.value)} className="h-8 w-full rounded-md border border-input bg-background px-2 text-sm">
                {mainStats.map((k) => <option key={k} value={k}>{k}</option>)}
              </select>
            </label>
          </div>

          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">Sub-stats (score ≤ {scoreMax.toFixed(1)}, budget {budget.toFixed(1)})</span>
              <span className={`text-xs ${subsTotal > budget ? "text-destructive" : "text-muted-foreground"}`}>total {subsTotal.toFixed(1)} / {budget.toFixed(1)}</span>
            </div>
            <SubStatRows slots={slots} options={subKeys} rows={shown} onChange={setSubs} />
            {shown.length < slots && (
              <Button variant="outline" size="sm" onClick={() => setSubs([...shown, { key: subKeys[0], value: "4" }])}>
                <Plus className="h-3.5 w-3.5 mr-1" /> Add sub-stat
              </Button>
            )}
          </div>

          <div className="flex flex-wrap gap-2">
            <Button onClick={addEntry} disabled={saving}>
              {saving ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Save className="h-4 w-4 mr-1" />} Add & Save
            </Button>
            <Button variant="outline" onClick={resetForm}>Reset</Button>
            {selectedId && (
              <Button variant="secondary" className="ml-auto" onClick={applyToPlayer}>
                <Check className="h-4 w-4 mr-1" /> Apply set to {selectedId}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
      {/* Saved admin set */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base"><Gem className="h-4 w-4 text-muted-foreground" /> Saved Admin Set ({adminList.length})</CardTitle>
          <CardDescription>These replace a player's accessories when you click "Apply set to player" (or via the Players tab's Admin Accessories macro). Persistent across restarts.</CardDescription>
        </CardHeader>
        <CardContent>
          {!adminList.length && <div className="py-6 text-center text-sm text-muted-foreground">No custom accessories saved yet. Add one above.</div>}
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {adminList.map((e: any, i: number) => (
              <Card key={i}>
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <CardTitle className="text-sm">{e.name || "Unnamed"}</CardTitle>
                      <CardDescription className="mt-0.5 text-xs">
                        {e.typeName || e.type} · rar {e.rarity} · lv {e.level} · {synNames.get(e.synergy) || e.synergy}
                      </CardDescription>
                    </div>
                    <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => deleteEntry(i)}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="pt-0">
                  <div className="rounded-md bg-muted/50 px-3 py-1.5 text-sm"><b>{e.mainStat}</b> <span className="text-xs text-muted-foreground">main</span></div>
                  <ul className="mt-1.5 space-y-0.5 text-sm">
                    {(e.subStats || []).map((s: any, j: number) => (
                      <li key={j} className="flex justify-between text-muted-foreground"><span>{s.key}</span><span>{s.value}</span></li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Owned accessories */}
      {selectedId && data && (
        <>
          <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
            <span className="flex items-center gap-1"><Info className="h-3.5 w-3.5" /> Grade thresholds (score): {Object.entries(data.scoreRange || {}).map(([g, v]: any) => `${g}=${v}`).join(" · ")}</span>
            <span>Grades: {Object.entries(data.grades || {}).map(([g, l]: any) => `${g}=${l}`).join(" · ")}</span>
          </div>
          {!data.accessories?.length && <Card><CardContent className="py-16 text-center text-muted-foreground">No accessories owned.</CardContent></Card>}
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {(data.accessories || []).map((a: any, i: number) => (
              <Card key={i}>
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between">
                    <div>
                      <CardTitle className="text-sm flex items-center gap-2">
                        <Gem className="h-4 w-4 text-muted-foreground" />
                        {a.typeName} #{a.id}
                      </CardTitle>
                      <CardDescription className="mt-1">
                        {a.synergyName} · {a.rarityName} · lv {a.level}
                        {a.unitName ? ` · ${a.unitName}` : ""}
                      </CardDescription>
                    </div>
                    <div className="text-right">
                      <div className="text-lg font-bold">{a.scoreTotal}</div>
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">score</div>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="pt-2">
                  {a.mainStatLabel && (
                    <div className="flex items-center justify-between rounded-md bg-muted/50 px-3 py-1.5 text-sm mb-2">
                      <span className="font-medium">{a.mainStatLabel}</span>
                      <span className="text-xs text-muted-foreground">main</span>
                    </div>
                  )}
                  <ul className="space-y-1">
                    {(a.subStats || []).map((s: any, j: number) => (
                      <li key={j} className="flex items-center justify-between text-sm">
                        <span className="text-muted-foreground">{s.label}</span>
                        <span className="flex items-center gap-2">
                          <span className="text-xs text-muted-foreground">score {s.score ?? "—"}</span>
                          {s.grade && <Badge variant="outline" className="text-[10px] px-1.5">{s.grade}</Badge>}
                        </span>
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            ))}
          </div>
        </>
      )}
      {!selectedId && <Card><CardContent className="py-16 text-center text-muted-foreground">Select a player above to view and apply accessories.</CardContent></Card>}
    </div>
  )
}
