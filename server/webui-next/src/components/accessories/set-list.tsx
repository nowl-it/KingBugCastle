"use client"

import { useState } from "react"
import { Check, Copy, Gem, Info, Loader2, Pencil, Search, Trash2 } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import type { AccessoryDraft, AdminEntry } from "./types"

export function AdminSetList({
  adminList,
  typeNames,
  rarityNames,
  synergyNames,
  includeBuiltin,
  builtinCount,
  deploymentCount,
  loading,
  selectedId,
  applying,
  draft,
  onApply,
  onToggleBuiltin,
  onEdit,
  onDelete,
}: {
  adminList: AdminEntry[]
  typeNames: Map<number, string>
  rarityNames: Map<number, string>
  synergyNames: Map<number, string>
  includeBuiltin: boolean
  builtinCount: number
  deploymentCount: number
  loading: boolean
  selectedId: string | null
  applying: boolean
  draft: AccessoryDraft | null
  onApply: () => void
  onToggleBuiltin: (include: boolean) => Promise<void> | void
  onEdit: (draft: AccessoryDraft) => void
  onDelete: (index: number) => Promise<void> | void
}) {
  const [query, setQuery] = useState("")
  const [toggling, setToggling] = useState(false)
  const [deleting, setDeleting] = useState<number | null>(null)

  const q = query.trim().toLowerCase()
  const filtered = adminList
    .map((entry, index) => ({ entry, index }))
    .filter(({ entry }) => !q || [entry.name, entry.type, entry.mainStat, synergyNames.get(entry.synergy)]
      .some((value) => String(value || "").toLowerCase().includes(q)))

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <div className="min-w-0">
          <CardTitle className="flex items-center gap-2"><Gem className="h-4 w-4 text-muted-foreground" /> 2. Review and apply set ({deploymentCount})</CardTitle>
          <CardDescription>{adminList.length} custom and {includeBuiltin ? builtinCount : 0} built-in accessories will be deployed.</CardDescription>
        </div>
        <Button onClick={onApply} disabled={!selectedId || !deploymentCount || applying} className="shrink-0">
          {applying ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Check className="mr-1.5 h-4 w-4" />} Apply entire set
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        <label htmlFor="include-builtin" className="flex cursor-pointer items-start gap-3 rounded-lg border bg-muted/25 p-3">
          <input
            id="include-builtin"
            type="checkbox"
            checked={includeBuiltin}
            disabled={loading || toggling}
            onChange={async (event) => {
              setToggling(true)
              try { await onToggleBuiltin(event.target.checked) } finally { setToggling(false) }
            }}
            className="mt-0.5 h-4 w-4 accent-primary"
          />
          <span>
            <span className="block text-sm font-medium">Include built-in best-in-slot collection</span>
            <span className="mt-0.5 block text-xs text-muted-foreground">Adds {builtinCount} curated accessories to the custom items below when applying.</span>
          </span>
        </label>
        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input id="set-search" aria-label="Search this set" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search this set..." className="pl-8" />
        </div>

        {loading ? (
          <div className="space-y-2">{[0, 1, 2].map((item) => <div key={item} className="h-16 animate-pulse rounded-lg bg-muted" />)}</div>
        ) : !adminList.length ? (
          <div className="grid h-56 place-items-center px-6 text-center text-sm text-muted-foreground">
            <div><Gem className="mx-auto mb-3 h-6 w-6" />No custom accessories yet.{includeBuiltin ? ` The ${builtinCount}-item built-in collection is still ready to apply.` : " Add the first item on the left."}</div>
          </div>
        ) : !filtered.length ? (
          <div className="grid h-32 place-items-center text-center text-sm text-muted-foreground">No accessories match “{query}”.</div>
        ) : (
          <ol className="max-h-[520px] divide-y divide-border overflow-y-auto rounded-lg border">
            {filtered.map(({ entry, index }) => {
              const isEditing = draft?.index === index
              return (
                <li key={`${entry.name}-${index}`} className={`group flex items-start gap-3 px-4 py-3 hover:bg-muted/30 ${isEditing ? "bg-muted/40" : ""}`}>
                  <span className="mt-0.5 font-mono text-xs tnum text-muted-foreground">{String(index + 1).padStart(2, "0")}</span>
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
                  <div className="flex shrink-0">
                    <Button variant="ghost" size="icon" aria-label={`Duplicate ${entry.name}`} title="Duplicate" className="h-8 w-8 text-muted-foreground" onClick={() => onEdit({ entry, index: null })}><Copy className="h-3.5 w-3.5" /></Button>
                    <Button variant="ghost" size="icon" aria-label={`Edit ${entry.name}`} title="Edit" className="h-8 w-8 text-muted-foreground" onClick={() => onEdit({ entry, index })}><Pencil className="h-3.5 w-3.5" /></Button>
                    <Button variant="ghost" size="icon" aria-label={`Remove ${entry.name || `accessory ${index + 1}`}`} title="Remove" disabled={deleting === index} className="h-8 w-8 text-muted-foreground hover:text-destructive" onClick={async () => {
                      setDeleting(index)
                      try { await onDelete(index) } finally { setDeleting(null) }
                    }}>
                      {deleting === index ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                    </Button>
                  </div>
                </li>
              )
            })}
          </ol>
        )}
      </CardContent>
      <CardFooter className="gap-2 bg-muted/30 text-xs leading-5 text-muted-foreground">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <p><b className="font-medium text-foreground">Apply entire set</b> deploys {deploymentCount} items and replaces everything currently owned by the selected player. Confirmation is required.</p>
      </CardFooter>
    </Card>
  )
}
