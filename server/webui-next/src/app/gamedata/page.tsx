"use client"

import { useState, useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import { fetcher } from "@/lib/api"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Search, Package, UserRound, ScrollText, Gem, Diamond, Shirt, Loader2 } from "lucide-react"

const TABS = [
  { key: "Hero", label: "Heroes", icon: UserRound, color: "text-blue-400" },
  { key: "Item", label: "Items", icon: Package, color: "text-amber-400" },
  { key: "Relic", label: "Relics", icon: ScrollText, color: "text-violet-400" },
  { key: "Treasure", label: "Treasures", icon: Gem, color: "text-emerald-400" },
  { key: "Accessory", label: "Accessories", icon: Diamond, color: "text-rose-400" },
  { key: "Skin", label: "Skins", icon: Shirt, color: "text-cyan-400" },
]

function Thumb({ entry }: { entry: any }) {
  const [broken, setBroken] = useState(false)
  const cls = "h-14 w-14 shrink-0 rounded-lg border border-border bg-muted object-cover"
  if (entry.image && !broken) {
    return (
      <img
        src={entry.image}
        alt={entry.name}
        onError={() => setBroken(true)}
        className={cls}
      />
    )
  }
  return (
    <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-lg border border-border bg-muted text-sm font-semibold text-muted-foreground">
      {(entry.name || "?").slice(0, 2)}
    </div>
  )
}

export default function GameDataPage() {
  const [tab, setTab] = useState("Hero")
  const [q, setQ] = useState("")
  const { data, isLoading } = useQuery({
    queryKey: ["/api/game-data"],
    queryFn: () => fetcher("/api/game-data"),
    refetchOnWindowFocus: false,
  })

  const rows = useMemo(() => {
    const list = (data && data[tab]) || []
    const query = q.trim().toLowerCase()
    if (!query) return list
    return list.filter((e: any) =>
      String(e.id).includes(query) ||
      (e.name || "").toLowerCase().includes(query) ||
      (e.role || "").toLowerCase().includes(query) ||
      (e.rarity || "").toLowerCase().includes(query) ||
      (e.fromType || "").toLowerCase().includes(query) ||
      (e.synergy || "").toLowerCase().includes(query) ||
      (e.unitName || "").toLowerCase().includes(query))
  }, [data, tab, q])

  const extraCols = (() => {
    switch (tab) {
      case "Hero": return [{ label: "Role", key: "role" }, { label: "Sprite", key: "sprite" }]
      case "Item": return [{ label: "Sub", key: "sub" }]
      case "Relic": return [{ label: "From", key: "fromType" }, { label: "Level", key: "level" }]
      case "Treasure": return [{ label: "Rarity", key: "rarity" }]
      case "Accessory": return [{ label: "Synergy", key: "synergy" }, { label: "Rarity", key: "rarity" }]
      case "Skin": return [{ label: "Unit", key: "unitName" }, { label: "Grade", key: "grade" }, { label: "Cash", key: "cashPrice" }]
      default: return []
    }
  })()

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Game Data</h1>
        <p className="text-muted-foreground">Full master-data browser — every hero, item, relic, treasure, accessory and skin with its in-game id.</p>
      </div>

      <div className="flex flex-wrap gap-2">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => { setTab(t.key); setQ("") }}
            className={`flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm font-medium transition-colors ${
              tab === t.key ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:bg-muted"
            }`}
          >
            <t.icon className={`h-4 w-4 ${t.color}`} />
            {t.label}
            {data && <span className="text-xs text-muted-foreground">{data[t.key]?.length || 0}</span>}
          </button>
        ))}
      </div>

      <div className="relative max-w-sm">
        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input placeholder={`Search ${tab.toLowerCase()} by id or name...`} value={q} onChange={(e) => setQ(e.target.value)} className="pl-8" />
      </div>

      {isLoading && !data && (
        <Card><CardContent className="py-16 flex items-center justify-center gap-3 text-muted-foreground">
          <Loader2 className="h-6 w-6 animate-spin text-primary" /> Loading master data...
        </CardContent></Card>
      )}

      {data && (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-16" />
                  <TableHead>ID</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Type</TableHead>
                  {extraCols.map((c) => <TableHead key={c.key}>{c.label}</TableHead>)}
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.slice(0, 300).map((e: any) => (
                  <TableRow key={`${tab}-${e.id}`}>
                    <TableCell><Thumb entry={e} /></TableCell>
                    <TableCell className="font-mono text-xs">{e.id}</TableCell>
                    <TableCell className="font-medium">{e.name}</TableCell>
                    <TableCell><Badge variant="outline" className="text-[10px]">{e.type}</Badge></TableCell>
                    {extraCols.map((c) => <TableCell key={c.key} className="text-xs text-muted-foreground">{e[c.key] ?? "—"}</TableCell>)}
                  </TableRow>
                ))}
                {!rows.length && (
                  <TableRow><TableCell colSpan={5 + extraCols.length} className="py-8 text-center text-muted-foreground">No match.</TableCell></TableRow>
                )}
              </TableBody>
            </Table>
            {rows.length > 300 && (
              <p className="px-4 py-3 text-xs text-muted-foreground">Showing first 300 of {rows.length} — refine the search.</p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}