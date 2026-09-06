"use client"

import { useState, type FormEvent } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  AlertTriangle,
  Check,
  Diamond,
  Gem,
  Info,
  Loader2,
  PackageOpen,
  Plus,
  RotateCcw,
  Save,
  Search,
  Trash2,
} from "lucide-react"
import { fetcher, runMutation, useAccessories } from "@/lib/api"
import { PlayerBar, usePlayerSelection } from "@/components/player-context"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

type BuilderChoice = { id: number; name: string }
type BuilderOptions = {
  types: BuilderChoice[]
  rarities: BuilderChoice[]
  synergies: BuilderChoice[]
  mainStatsByType: Record<string, string[]>
  subStatKeys: string[]
  scoreMax: number
  slotsByRarity: Record<string, number>
  budgetByRarity: Record<string, number>
}
type AdminEntry = {
  name: string
  type: number | string
  rarity: number
  level: number
  synergy: number
  mainStat: string
  subStats: { key: string; value: number }[]
}
type AdminConfig = { include_builtin: boolean; accessories: AdminEntry[] }
type AccessorySubStat = { label: string; score?: number; grade?: string }
type Accessory = {
  id: number
  typeName: string
  synergyName: string
  rarityName: string
  level: number
  unitName?: string
  scoreTotal: number
  mainStatLabel?: string
  subStats?: AccessorySubStat[]
}
type AccessoriesResponse = {
  scoreRange?: Record<string, string | number>
  grades?: Record<string, string | number>
  accessories?: Accessory[]
}
type SubStatRow = { key: string; value: string }

const fieldClass = "h-10 w-full rounded-md border border-input bg-background px-3 text-sm outline-none transition-colors focus:border-foreground focus:ring-2 focus:ring-ring/20"

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="grid gap-1.5">
      <span className="flex items-center justify-between gap-3 text-xs font-medium text-foreground">
        {label}
        {hint && <span className="font-mono font-normal text-muted-foreground">{hint}</span>}
      </span>
      {children}
    </label>
  )
}

function SubStatRows({
  options,
  rows,
  max,
  onChange,
}: {
  options: string[]
  rows: SubStatRow[]
  max: number
  onChange: (rows: SubStatRow[]) => void
}) {
  const set = (index: number, patch: Partial<SubStatRow>) => {
    onChange(rows.map((row, i) => i === index ? { ...row, ...patch } : row))
  }

  return (
    <div className="grid gap-2">
      {rows.map((row, index) => (
        <div key={index} className="grid grid-cols-[minmax(0,1fr)_5.5rem_2.25rem] items-center gap-2">
          <select
            aria-label={`Sub-stat ${index + 1}`}
            value={row.key}
            onChange={(event) => set(index, { key: event.target.value })}
            className={fieldClass}
          >
            {options.map((key) => <option key={key} value={key}>{key}</option>)}
          </select>
          <Input
            aria-label={`Sub-stat ${index + 1} score`}
            type="number"
            step="0.1"
            min={0}
            max={max}
            value={row.value}
            onChange={(event) => set(index, { value: event.target.value })}
            className="font-mono tabular-nums"
          />
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={`Remove sub-stat ${index + 1}`}
            disabled={rows.length === 1}
            className="h-9 w-9 text-muted-foreground hover:text-destructive"
            onClick={() => onChange(rows.filter((_, i) => i !== index))}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ))}
    </div>
  )
}

export default function AccessoriesPage() {
  const { selectedId } = usePlayerSelection()
  const { data, mutate: mutateAccessories } = useAccessories(selectedId || undefined)
  const { data: optionsData, isLoading: optionsLoading, isError: optionsError } = useQuery({
    queryKey: ["/api/admin-accessories/options"],
    queryFn: () => fetcher("/api/admin-accessories/options"),
  })
  const { data: configData, refetch: refetchConfig, isLoading: configLoading } = useQuery({
    queryKey: ["/api/admin-accessories"],
    queryFn: () => fetcher("/api/admin-accessories"),
  })

  const [name, setName] = useState("")
  const [type, setType] = useState("Necklace")
  const [rarity, setRarity] = useState("3")
  const [level, setLevel] = useState("20")
  const [synergy, setSynergy] = useState("0")
  const [mainStat, setMainStat] = useState("AtkPer")
  const [subStats, setSubStats] = useState<SubStatRow[]>([{ key: "BaseDefPen", value: "26" }])
  const [saving, setSaving] = useState(false)
  const [applying, setApplying] = useState(false)
  const [deleting, setDeleting] = useState<number | null>(null)
  const [view, setView] = useState<"build" | "inventory">("build")
  const [setQuery, setSetQuery] = useState("")

  const options = optionsData as BuilderOptions | undefined
  const config = configData as AdminConfig | undefined
  const owned = data as AccessoriesResponse | undefined
  const adminList = config?.accessories || []
  const mainStats = options?.mainStatsByType[type] || []
  const slots = options?.slotsByRarity[rarity] || 1
  const budget = options?.budgetByRarity[rarity] || 0
  const subKeys = options?.subStatKeys || []
  const scoreMax = options?.scoreMax ?? 26
  const shownSubStats = subStats.slice(0, slots)
  const subStatsTotal = shownSubStats.reduce((total, row) => total + (parseFloat(row.value) || 0), 0)
  const budgetPercent = budget ? Math.min(100, (subStatsTotal / budget) * 100) : 0
  const overBudget = subStatsTotal > budget + 0.001
  const canSave = Boolean(name.trim()) && !overBudget && !optionsLoading && !optionsError
  const typeNames = new Map((options?.types || []).map((entry) => [entry.id, entry.name]))
  const rarityNames = new Map((options?.rarities || []).map((entry) => [entry.id, entry.name]))
  const synergyNames = new Map((options?.synergies || []).map((entry) => [entry.id, entry.name]))
  const query = setQuery.trim().toLowerCase()
  const filteredAdminList = adminList
    .map((entry, index) => ({ entry, index }))
    .filter(({ entry }) => !query || [entry.name, entry.type, entry.mainStat, synergyNames.get(entry.synergy)]
      .some((value) => String(value || "").toLowerCase().includes(query)))

  const resetForm = () => {
    setName("")
    setType("Necklace")
    setRarity("3")
    setLevel("20")
    setSynergy("0")
    setMainStat(options?.mainStatsByType.Necklace?.[0] || "AtkPer")
    setSubStats([{ key: subKeys[0] || "AtkPer", value: "26" }])
  }

  const addEntry = async (event: FormEvent) => {
    event.preventDefault()
    if (!canSave) return
    setSaving(true)
    try {
      await runMutation("/api/admin-accessories", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          type,
          rarity: Number(rarity),
          level: Number(level),
          synergy: Number(synergy),
          mainStat,
          subStats: shownSubStats.map((row) => ({ key: row.key, value: parseFloat(row.value) || 0 })),
        }),
      }, "Accessory saved to the admin set")
      resetForm()
      refetchConfig()
    } finally {
      setSaving(false)
    }
  }

  const deleteEntry = async (index: number) => {
    setDeleting(index)
    try {
      await runMutation("/api/admin-accessories/delete", {
        method: "POST",
        body: JSON.stringify({ index }),
      }, "Accessory removed")
      refetchConfig()
    } finally {
      setDeleting(null)
    }
  }

  const applyToPlayer = async () => {
    if (!selectedId || !adminList.length) return
    setApplying(true)
    try {
      await runMutation("/api/admin-accessories/apply", {
        method: "POST",
        body: JSON.stringify({ pid: selectedId }),
      }, "Admin set applied to player")
      mutateAccessories()
    } finally {
      setApplying(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Accessories</h1>
        <p className="text-muted-foreground">Build one admin set, then replace a player&apos;s accessories with it.</p>
      </div>

      <PlayerBar />

      <div className="grid gap-px overflow-hidden rounded-lg border bg-border sm:grid-cols-3">
        {[
          ["1", "Add accessories", "Each save adds one item to the admin set."],
          ["2", "Review the set", `The set currently contains ${adminList.length} item${adminList.length === 1 ? "" : "s"}.`],
          ["3", "Apply to player", "Apply replaces the selected player's current set."],
        ].map(([step, title, description]) => (
          <div key={step} className="flex gap-3 bg-card p-4">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">{step}</span>
            <div>
              <p className="text-sm font-medium">{title}</p>
              <p className="mt-0.5 text-xs leading-5 text-muted-foreground">{description}</p>
            </div>
          </div>
        ))}
      </div>

      {optionsError && (
        <div role="alert" className="flex items-center gap-3 border-l-2 border-destructive bg-destructive/5 px-4 py-3 text-sm text-destructive">
          <AlertTriangle className="h-4 w-4 shrink-0" /> Builder rules could not be loaded. Refresh before creating an accessory.
        </div>
      )}

      <div className="flex w-fit rounded-md border bg-muted/40 p-1" role="tablist" aria-label="Accessory workspace">
        <button
          role="tab"
          aria-selected={view === "build"}
          onClick={() => setView("build")}
          className={`rounded px-3 py-1.5 text-sm font-medium transition-colors ${view === "build" ? "bg-background shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
        >
          Build set <span className="ml-1 text-xs text-muted-foreground">{adminList.length}</span>
        </button>
        <button
          role="tab"
          aria-selected={view === "inventory"}
          onClick={() => setView("inventory")}
          className={`rounded px-3 py-1.5 text-sm font-medium transition-colors ${view === "inventory" ? "bg-background shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
        >
          Player inventory <span className="ml-1 text-xs text-muted-foreground">{owned?.accessories?.length ?? 0}</span>
        </button>
      </div>

      {view === "build" ? (
        <div className="grid items-start gap-6 xl:grid-cols-[minmax(360px,480px)_minmax(0,1fr)]">
          <form onSubmit={addEntry} className="xl:sticky xl:top-20">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base"><Diamond className="h-4 w-4" /> 1. Add one accessory</CardTitle>
                <CardDescription>Saving adds this accessory to the set shown on the right. It does not change a player yet.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <Field label="Name" hint="required">
                  <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Menace necklace" autoComplete="off" />
                </Field>

                <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-2">
                  <Field label="Type">
                    <select
                      value={type}
                      onChange={(event) => {
                        setType(event.target.value)
                        setMainStat(options?.mainStatsByType[event.target.value]?.[0] || "AtkPer")
                      }}
                      className={fieldClass}
                    >
                      {(options?.types || []).map((entry) => <option key={entry.id} value={entry.name}>{entry.name}</option>)}
                    </select>
                  </Field>
                  <Field label="Rarity" hint={`${slots} stats`}>
                    <select value={rarity} onChange={(event) => setRarity(event.target.value)} className={fieldClass}>
                      {(options?.rarities || []).map((entry) => <option key={entry.id} value={String(entry.id)}>{entry.name}</option>)}
                    </select>
                  </Field>
                  <Field label="Level">
                    <Input type="number" min={1} max={20} value={level} onChange={(event) => setLevel(event.target.value)} className="font-mono tabular-nums" />
                  </Field>
                  <Field label="Synergy">
                    <select value={synergy} onChange={(event) => setSynergy(event.target.value)} className={fieldClass}>
                      {(options?.synergies || []).map((entry) => <option key={entry.id} value={String(entry.id)}>{entry.name}</option>)}
                    </select>
                  </Field>
                </div>

                <Field label="Main stat" hint={type}>
                  <select value={mainStat} onChange={(event) => setMainStat(event.target.value)} className={fieldClass}>
                    {mainStats.map((key) => <option key={key} value={key}>{key}</option>)}
                  </select>
                </Field>

                <fieldset className="space-y-3 rounded-md border p-3">
                  <div className="flex items-center justify-between gap-3">
                    <legend className="text-xs font-medium">Sub-stats</legend>
                    <span className={`font-mono text-xs tabular-nums ${overBudget ? "text-destructive" : "text-muted-foreground"}`}>
                      {subStatsTotal.toFixed(1)} / {budget.toFixed(1)} points
                    </span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                    <div className={`h-full rounded-full transition-all ${overBudget ? "bg-destructive" : "bg-primary"}`} style={{ width: `${budgetPercent}%` }} />
                  </div>
                  <SubStatRows options={subKeys} rows={shownSubStats} max={scoreMax} onChange={setSubStats} />
                  <div className="flex items-center justify-between gap-3">
                    {shownSubStats.length < slots ? (
                      <Button type="button" variant="outline" size="sm" onClick={() => setSubStats([...shownSubStats, { key: subKeys[0] || "AtkPer", value: "4" }])}>
                        <Plus className="mr-1 h-3.5 w-3.5" /> Add stat
                      </Button>
                    ) : <span />}
                    <span className="text-xs text-muted-foreground">Max {scoreMax.toFixed(1)} each</span>
                  </div>
                  {overBudget && <p className="text-xs font-medium text-destructive">Reduce the total by {(subStatsTotal - budget).toFixed(1)} points.</p>}
                </fieldset>

                <div className="flex flex-col-reverse gap-2 border-t pt-4 sm:flex-row sm:justify-between">
                  <Button type="button" variant="ghost" onClick={resetForm}><RotateCcw className="mr-1.5 h-4 w-4" /> Reset</Button>
                  <Button type="submit" disabled={!canSave || saving}>
                    {saving ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Save className="mr-1.5 h-4 w-4" />} Add to set
                  </Button>
                </div>
              </CardContent>
            </Card>
          </form>

          <Card className="overflow-hidden">
            <CardHeader className="pb-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <CardTitle className="flex items-center gap-2 text-base"><Gem className="h-4 w-4" /> 2. Review and apply set ({adminList.length})</CardTitle>
                  <CardDescription className="mt-1">Every item below belongs to the same admin set.</CardDescription>
                </div>
                <Button onClick={applyToPlayer} disabled={!selectedId || !adminList.length || applying} className="shrink-0">
                  {applying ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Check className="mr-1.5 h-4 w-4" />} Apply entire set
                </Button>
              </div>
              <div className="relative mt-2">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input value={setQuery} onChange={(event) => setSetQuery(event.target.value)} placeholder="Search this set..." className="pl-8" />
              </div>
            </CardHeader>

            <CardContent className="p-0">
              {configLoading ? (
                <div className="space-y-2 p-4">{[0, 1, 2].map((item) => <div key={item} className="h-16 animate-pulse rounded bg-muted" />)}</div>
              ) : !adminList.length ? (
                <div className="grid h-64 place-items-center px-6 text-center text-sm text-muted-foreground">
                  <div><Gem className="mx-auto mb-3 h-6 w-6" />The admin set is empty. Add the first accessory on the left.</div>
                </div>
              ) : !filteredAdminList.length ? (
                <div className="grid h-40 place-items-center px-6 text-center text-sm text-muted-foreground">No accessories match “{setQuery}”.</div>
              ) : (
                <ol className="max-h-[570px] divide-y divide-border overflow-y-auto">
                  {filteredAdminList.map(({ entry, index }) => (
                    <li key={`${entry.name}-${index}`} className="group flex items-start gap-3 px-4 py-3 hover:bg-muted/30">
                      <span className="mt-0.5 font-mono text-xs text-muted-foreground">{String(index + 1).padStart(2, "0")}</span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="truncate text-sm font-medium">{entry.name || "Unnamed"}</span>
                          <Badge variant="outline" className="rounded px-1.5 py-0 text-[10px]">Lv {entry.level}</Badge>
                        </div>
                        <p className="mt-0.5 truncate text-xs text-muted-foreground">
                          {typeof entry.type === "number" ? typeNames.get(entry.type) || entry.type : entry.type} · {rarityNames.get(entry.rarity) || `Rarity ${entry.rarity}`} · {synergyNames.get(entry.synergy) || entry.synergy}
                        </p>
                        <p className="mt-1 truncate text-xs"><b className="font-medium">{entry.mainStat}</b> <span className="text-muted-foreground">main · {(entry.subStats || []).map((stat) => `${stat.key} ${stat.value}`).join(" · ")}</span></p>
                      </div>
                      <Button variant="ghost" size="icon" aria-label={`Remove ${entry.name || `accessory ${index + 1}`}`} disabled={deleting === index} className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive" onClick={() => deleteEntry(index)}>
                        {deleting === index ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                      </Button>
                    </li>
                  ))}
                </ol>
              )}
              <div className="flex items-start gap-2 border-t bg-muted/30 px-4 py-3 text-xs leading-5 text-muted-foreground">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <p><b className="font-medium text-foreground">Apply entire set</b> replaces all accessories owned by the player selected above. It does not merge.</p>
              </div>
            </CardContent>
          </Card>
        </div>
      ) : (
        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base"><PackageOpen className="h-4 w-4" /> Player inventory</CardTitle>
            <CardDescription>Read-only view of the accessories currently owned by the selected player.</CardDescription>
            {selectedId && owned && (
              <details className="pt-1 text-xs text-muted-foreground">
                <summary className="cursor-pointer font-medium text-foreground">Scoring reference</summary>
                <p className="mt-2 leading-5">Thresholds: {Object.entries(owned.scoreRange || {}).map(([grade, value]) => `${grade} ${value}`).join(" · ") || "none"}<br />Grades: {Object.entries(owned.grades || {}).map(([grade, label]) => `${grade} ${label}`).join(" · ") || "none"}</p>
              </details>
            )}
          </CardHeader>
          <CardContent className="p-0">
            {!selectedId ? (
              <div className="grid h-48 place-items-center text-sm text-muted-foreground">Select a player above.</div>
            ) : !owned ? (
              <div className="space-y-2 p-4">{[0, 1, 2].map((item) => <div key={item} className="h-14 animate-pulse rounded bg-muted" />)}</div>
            ) : !owned.accessories?.length ? (
              <div className="grid h-48 place-items-center text-sm text-muted-foreground">This player owns no accessories.</div>
            ) : (
              <div className="max-h-[65vh] overflow-auto">
                <table className="w-full min-w-[760px] border-collapse text-left text-sm">
                  <thead className="sticky top-0 z-10 bg-muted text-xs text-muted-foreground">
                    <tr><th className="px-4 py-3 font-medium">Accessory</th><th className="px-4 py-3 font-medium">Main stat</th><th className="px-4 py-3 font-medium">Sub-stats</th><th className="px-4 py-3 text-right font-medium">Score</th></tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {owned.accessories.map((accessory) => (
                      <tr key={accessory.id} className="align-top hover:bg-muted/20">
                        <td className="px-4 py-3">
                          <span className="font-medium">{accessory.typeName} <span className="font-mono font-normal text-muted-foreground">#{accessory.id}</span></span>
                          <span className="mt-0.5 block text-xs text-muted-foreground">{accessory.rarityName} · Lv {accessory.level} · {accessory.synergyName}{accessory.unitName ? ` · ${accessory.unitName}` : ""}</span>
                        </td>
                        <td className="px-4 py-3 font-medium">{accessory.mainStatLabel || "—"}</td>
                        <td className="px-4 py-3 text-xs text-muted-foreground">{(accessory.subStats || []).map((stat) => `${stat.label} ${stat.score ?? "—"}${stat.grade ? ` (${stat.grade})` : ""}`).join(" · ") || "—"}</td>
                        <td className="px-4 py-3 text-right font-mono text-base font-semibold tabular-nums">{accessory.scoreTotal}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
