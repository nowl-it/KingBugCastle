"use client"

import { useState, type FormEvent } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  AlertTriangle,
  Check,
  ChevronRight,
  Diamond,
  Gem,
  Loader2,
  PackageOpen,
  Plus,
  RotateCcw,
  Save,
  ShieldCheck,
  Sparkles,
  Trash2,
  UserRound,
} from "lucide-react"
import { fetcher, runMutation, useAccessories, usePlayers } from "@/lib/api"
import { usePlayerSelection } from "@/components/player-context"
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
type PlayerSummary = { id: string; name: string; active?: boolean }
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
  const { selectedId, setSelectedId } = usePlayerSelection()
  const { data: playerData } = usePlayers()
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

  const players = (Array.isArray(playerData) ? playerData : []) as PlayerSummary[]
  const selectedPlayer = players.find((player) => player.id === selectedId)
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
    <div className="mx-auto max-w-[1500px] space-y-6 pb-10">
      <header className="relative overflow-hidden rounded-xl bg-zinc-950 px-5 py-6 text-zinc-100 shadow-[0_24px_70px_-42px_rgba(0,0,0,0.9)] sm:px-7 sm:py-8">
        <div className="pointer-events-none absolute -right-16 -top-24 h-72 w-72 rounded-full border border-amber-300/10 shadow-[0_0_0_45px_rgba(251,191,36,0.025),0_0_0_90px_rgba(251,191,36,0.015)]" />
        <div className="relative grid gap-6 xl:grid-cols-[minmax(0,1fr)_24rem] xl:items-end">
          <div>
            <p className="mb-3 flex items-center gap-2 font-mono text-[11px] font-semibold uppercase tracking-[0.2em] text-amber-300/80">
              <Sparkles className="h-3.5 w-3.5" /> Loadout operations
            </p>
            <h1 className="max-w-3xl text-3xl font-semibold tracking-[-0.04em] sm:text-4xl">Accessory forge</h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-zinc-400">
              Build a legal loadout, review it as one set, then deploy it to a player. Deployment replaces that player&apos;s current accessories.
            </p>
          </div>
          <label className="grid gap-2 rounded-lg border border-white/10 bg-white/[0.04] p-4 backdrop-blur-sm">
            <span className="flex items-center justify-between text-xs font-medium text-zinc-300">
              <span className="flex items-center gap-2"><UserRound className="h-4 w-4 text-amber-300" /> Deployment target</span>
              {selectedPlayer?.active && <span className="font-mono text-[10px] uppercase tracking-wider text-emerald-300">Active</span>}
            </span>
            <select
              value={selectedId || ""}
              onChange={(event) => setSelectedId(event.target.value)}
              className="h-11 w-full rounded-md border border-white/10 bg-zinc-900 px-3 text-sm text-zinc-100 outline-none transition-colors focus:border-amber-300/60 focus:ring-2 focus:ring-amber-300/10"
            >
              <option value="" disabled>Select a player...</option>
              {players.map((player) => (
                <option key={player.id} value={player.id}>{player.name} · {player.id}</option>
              ))}
            </select>
          </label>
        </div>
        <ol className="relative mt-7 grid gap-2 border-t border-white/10 pt-5 sm:grid-cols-3">
          {[
            ["01", "Configure", "Choose legal game stats"],
            ["02", "Assemble", `${adminList.length} item${adminList.length === 1 ? "" : "s"} in saved set`],
            ["03", "Deploy", selectedPlayer ? `Target: ${selectedPlayer.name}` : "Choose a target"],
          ].map(([step, title, detail], index) => (
            <li key={step} className="flex items-center gap-3 rounded-md px-2 py-2 sm:px-3">
              <span className="font-mono text-xs text-amber-300/70">{step}</span>
              <span className="min-w-0">
                <span className="block text-xs font-semibold text-zinc-200">{title}</span>
                <span className="block truncate text-[11px] text-zinc-500">{detail}</span>
              </span>
              {index < 2 && <ChevronRight className="ml-auto hidden h-4 w-4 text-zinc-700 sm:block" />}
            </li>
          ))}
        </ol>
      </header>

      {optionsError && (
        <div role="alert" className="flex items-center gap-3 border-l-2 border-destructive bg-destructive/5 px-4 py-3 text-sm text-destructive">
          <AlertTriangle className="h-4 w-4 shrink-0" /> Builder rules could not be loaded. Refresh before creating an accessory.
        </div>
      )}

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,0.92fr)_minmax(34rem,1.08fr)]">
        <form onSubmit={addEntry} className="overflow-hidden rounded-xl border bg-card xl:sticky xl:top-20">
          <div className="border-b bg-muted/35 px-5 py-4 sm:px-6">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">Blueprint</p>
                <h2 className="mt-1 text-lg font-semibold tracking-tight">Configure accessory</h2>
              </div>
              <Diamond className="h-6 w-6 text-amber-500" />
            </div>
          </div>

          <div className="grid gap-6 p-5 sm:p-6">
            <Field label="Display name" hint="required">
              <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Menace necklace" autoComplete="off" />
            </Field>

            <fieldset className="grid gap-3">
              <legend className="mb-1 text-xs font-semibold text-muted-foreground">Base properties</legend>
              <div className="grid gap-3 sm:grid-cols-2">
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
                <Field label="Rarity" hint={`${slots} slot${slots === 1 ? "" : "s"}`}>
                  <select value={rarity} onChange={(event) => setRarity(event.target.value)} className={fieldClass}>
                    {(options?.rarities || []).map((entry) => <option key={entry.id} value={String(entry.id)}>{entry.name}</option>)}
                  </select>
                </Field>
                <Field label="Level" hint="1–20">
                  <Input type="number" min={1} max={20} value={level} onChange={(event) => setLevel(event.target.value)} className="font-mono tabular-nums" />
                </Field>
                <Field label="Synergy">
                  <select value={synergy} onChange={(event) => setSynergy(event.target.value)} className={fieldClass}>
                    {(options?.synergies || []).map((entry) => <option key={entry.id} value={String(entry.id)}>{entry.name}</option>)}
                  </select>
                </Field>
              </div>
            </fieldset>

            <Field label="Main stat" hint={type}>
              <select value={mainStat} onChange={(event) => setMainStat(event.target.value)} className={fieldClass}>
                {mainStats.map((key) => <option key={key} value={key}>{key}</option>)}
              </select>
            </Field>

            <fieldset className="grid gap-3">
              <div className="flex items-end justify-between gap-4">
                <legend className="text-xs font-semibold text-muted-foreground">Sub-stats</legend>
                <span className={`font-mono text-xs font-semibold tabular-nums ${overBudget ? "text-destructive" : "text-foreground"}`}>
                  {subStatsTotal.toFixed(1)} / {budget.toFixed(1)}
                </span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                <div
                  className={`h-full rounded-full transition-[width,background-color] duration-300 ${overBudget ? "bg-destructive" : "bg-amber-500"}`}
                  style={{ width: `${budgetPercent}%` }}
                />
              </div>
              <p className="text-xs leading-5 text-muted-foreground">Shared score budget across {slots} slot{slots === 1 ? "" : "s"}. Each stat accepts up to {scoreMax.toFixed(1)}.</p>
              <SubStatRows options={subKeys} rows={shownSubStats} max={scoreMax} onChange={setSubStats} />
              {shownSubStats.length < slots && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="justify-self-start"
                  onClick={() => setSubStats([...shownSubStats, { key: subKeys[0] || "AtkPer", value: "4" }])}
                >
                  <Plus className="mr-1.5 h-3.5 w-3.5" /> Add stat slot
                </Button>
              )}
              {overBudget && <p className="text-xs font-medium text-destructive">Reduce the total by {(subStatsTotal - budget).toFixed(1)} points to save.</p>}
            </fieldset>

            <div className="rounded-lg bg-zinc-950 p-4 text-zinc-100">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold">{name.trim() || "Unnamed accessory"}</p>
                  <p className="mt-1 text-xs text-zinc-500">{type} · {rarityNames.get(Number(rarity)) || `Rarity ${rarity}`} · Lv {level || "—"}</p>
                </div>
                <span className="font-mono text-xl font-semibold text-amber-300 tabular-nums">{subStatsTotal.toFixed(1)}</span>
              </div>
              <div className="mt-4 flex items-center justify-between border-t border-white/10 pt-3 text-xs">
                <span className="font-medium text-zinc-300">{mainStat || "No main stat"}</span>
                <span className="text-zinc-600">main stat</span>
              </div>
            </div>
          </div>

          <div className="flex flex-col-reverse gap-2 border-t bg-muted/25 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <Button type="button" variant="ghost" onClick={resetForm}>
              <RotateCcw className="mr-1.5 h-4 w-4" /> Reset
            </Button>
            <Button type="submit" disabled={!canSave || saving} className="sm:min-w-36">
              {saving ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Save className="mr-1.5 h-4 w-4" />}
              Save to set
            </Button>
          </div>
        </form>

        <section aria-labelledby="saved-set-heading" className="overflow-hidden rounded-xl border bg-card">
          <div className="flex flex-col gap-4 border-b px-5 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <div>
              <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">Deployment manifest</p>
              <h2 id="saved-set-heading" className="mt-1 flex items-center gap-2 text-lg font-semibold tracking-tight">
                Saved admin set <span className="font-mono text-sm font-normal text-muted-foreground">({adminList.length})</span>
              </h2>
              <p className="mt-1 text-xs text-muted-foreground">Persistent across restarts. Applying this manifest replaces the target&apos;s current set.</p>
            </div>
            <Button
              onClick={applyToPlayer}
              disabled={!selectedId || !adminList.length || applying}
              className="shrink-0 bg-amber-400 text-zinc-950 hover:bg-amber-300"
            >
              {applying ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Check className="mr-1.5 h-4 w-4" />}
              Deploy set
            </Button>
          </div>

          {configLoading ? (
            <div className="grid gap-3 p-5 sm:p-6">
              {[0, 1, 2].map((item) => <div key={item} className="h-20 animate-pulse rounded-md bg-muted" />)}
            </div>
          ) : !adminList.length ? (
            <div className="grid min-h-72 place-items-center px-6 py-12 text-center">
              <div>
                <div className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-muted text-muted-foreground"><Gem className="h-5 w-5" /></div>
                <h3 className="mt-4 text-sm font-semibold">The manifest is empty</h3>
                <p className="mx-auto mt-1 max-w-sm text-xs leading-5 text-muted-foreground">Configure an accessory in the forge and save it here before deploying.</p>
              </div>
            </div>
          ) : (
            <ol className="divide-y divide-border">
              {adminList.map((entry, index) => (
                <li key={`${entry.name}-${index}`} className="group grid gap-4 px-5 py-4 transition-colors hover:bg-muted/25 sm:grid-cols-[2rem_minmax(0,1fr)_auto] sm:items-center sm:px-6">
                  <span className="hidden font-mono text-xs text-muted-foreground sm:block">{String(index + 1).padStart(2, "0")}</span>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="truncate text-sm font-semibold">{entry.name || "Unnamed"}</h3>
                      <Badge variant="outline" className="rounded-md px-1.5 py-0 font-mono text-[10px]">Lv {entry.level}</Badge>
                    </div>
                    <p className="mt-1 truncate text-xs text-muted-foreground">
                      {typeof entry.type === "number" ? typeNames.get(entry.type) || entry.type : entry.type}
                      <span className="mx-1.5 text-border">/</span>{rarityNames.get(entry.rarity) || `Rarity ${entry.rarity}`}
                      <span className="mx-1.5 text-border">/</span>{synergyNames.get(entry.synergy) || entry.synergy}
                    </p>
                    <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                      <span className="font-medium text-foreground">{entry.mainStat} <span className="font-normal text-muted-foreground">main</span></span>
                      {(entry.subStats || []).map((stat, statIndex) => (
                        <span key={`${stat.key}-${statIndex}`} className="text-muted-foreground">{stat.key} <b className="font-mono font-medium text-foreground tabular-nums">{stat.value}</b></span>
                      ))}
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Remove ${entry.name || `accessory ${index + 1}`}`}
                    disabled={deleting === index}
                    className="h-9 w-9 justify-self-end text-muted-foreground opacity-100 hover:text-destructive sm:opacity-0 sm:group-hover:opacity-100 sm:focus-visible:opacity-100"
                    onClick={() => deleteEntry(index)}
                  >
                    {deleting === index ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                  </Button>
                </li>
              ))}
            </ol>
          )}

          <div className="flex items-start gap-3 border-t bg-amber-400/10 px-5 py-4 text-xs leading-5 sm:px-6">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
            <p><b className="font-semibold">Destructive deployment:</b> {selectedPlayer ? `${selectedPlayer.name}'s` : "the selected player's"} existing accessories will be replaced, not merged.</p>
          </div>
        </section>
      </div>

      <section aria-labelledby="inventory-heading" className="overflow-hidden rounded-xl border bg-card">
        <div className="flex flex-col gap-3 border-b px-5 py-5 sm:flex-row sm:items-end sm:justify-between sm:px-6">
          <div>
            <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">Target inventory</p>
            <h2 id="inventory-heading" className="mt-1 flex items-center gap-2 text-lg font-semibold tracking-tight">
              <PackageOpen className="h-5 w-5 text-muted-foreground" /> Current accessories
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              {selectedPlayer ? `${selectedPlayer.name} · ${selectedPlayer.id}` : "Choose a deployment target above"}
            </p>
          </div>
          {selectedId && owned && (
            <details className="text-xs text-muted-foreground sm:text-right">
              <summary className="cursor-pointer select-none font-medium text-foreground hover:underline">Scoring reference</summary>
              <p className="mt-2 max-w-xl leading-5">
                Thresholds: {Object.entries(owned.scoreRange || {}).map(([grade, value]) => `${grade} ${value}`).join(" · ") || "none"}<br />
                Grades: {Object.entries(owned.grades || {}).map(([grade, label]) => `${grade} ${label}`).join(" · ") || "none"}
              </p>
            </details>
          )}
        </div>

        {!selectedId ? (
          <div className="grid min-h-48 place-items-center px-6 py-10 text-center text-sm text-muted-foreground">
            <div><UserRound className="mx-auto mb-3 h-6 w-6" />Select a player in the header to inspect their inventory.</div>
          </div>
        ) : !owned ? (
          <div className="grid gap-3 p-5 sm:p-6">
            {[0, 1, 2].map((item) => <div key={item} className="h-16 animate-pulse rounded-md bg-muted" />)}
          </div>
        ) : !owned.accessories?.length ? (
          <div className="grid min-h-48 place-items-center px-6 py-10 text-center text-sm text-muted-foreground">
            <div><Gem className="mx-auto mb-3 h-6 w-6" />This player owns no accessories.</div>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-left text-sm">
              <thead className="bg-muted/35 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="px-6 py-3 font-medium">Accessory</th>
                  <th className="px-4 py-3 font-medium">Main stat</th>
                  <th className="px-4 py-3 font-medium">Sub-stats</th>
                  <th className="px-6 py-3 text-right font-medium">Score</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {owned.accessories.map((accessory) => (
                  <tr key={accessory.id} className="align-top transition-colors hover:bg-muted/20">
                    <td className="px-6 py-4">
                      <div className="flex items-start gap-3">
                        <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground"><Gem className="h-4 w-4" /></span>
                        <span>
                          <span className="block font-semibold">{accessory.typeName} <span className="font-mono font-normal text-muted-foreground">#{accessory.id}</span></span>
                          <span className="mt-1 block text-xs text-muted-foreground">{accessory.rarityName} · Lv {accessory.level} · {accessory.synergyName}</span>
                          {accessory.unitName && <span className="mt-1 block text-xs font-medium text-amber-700 dark:text-amber-300">Equipped by {accessory.unitName}</span>}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-4 font-medium">{accessory.mainStatLabel || "—"}</td>
                    <td className="px-4 py-4">
                      <div className="flex max-w-xl flex-wrap gap-1.5">
                        {(accessory.subStats || []).map((stat, index) => (
                          <span key={`${stat.label}-${index}`} className="inline-flex items-center gap-1.5 rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground">
                            {stat.label}
                            <b className="font-mono font-medium text-foreground tabular-nums">{stat.score ?? "—"}</b>
                            {stat.grade && <span className="text-[10px] text-amber-700 dark:text-amber-300">{stat.grade}</span>}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-6 py-4 text-right font-mono text-lg font-semibold tabular-nums">{accessory.scoreTotal}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
