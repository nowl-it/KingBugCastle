"use client"

import { useAccessories } from "@/lib/api"
import { PlayerBar, usePlayerSelection } from "@/components/player-context"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Gem, Info } from "lucide-react"

type AccessorySubStat = { label: string; score?: number; grade?: string }
type Accessory = {
  id: number; typeName: string; synergyName: string; rarityName: string; level: number
  unitName?: string; scoreTotal: number; mainStatLabel?: string; subStats?: AccessorySubStat[]
}
type AccessoriesResponse = {
  scoreRange?: Record<string, string | number>; grades?: Record<string, string | number>; accessories?: Accessory[]
}

export default function AccessoriesPage() {
  const { selectedId } = usePlayerSelection()
  const { data } = useAccessories(selectedId || undefined)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Accessories</h1>
        <p className="text-muted-foreground">Read-only view of owned accessories (granting them directly is unsafe — use an Item reward box instead).</p>
      </div>
      <PlayerBar />
      {!selectedId && <Card><CardContent className="py-16 text-center text-muted-foreground">Select a player above.</CardContent></Card>}
      {selectedId && data && (
        <>
          <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
            <span className="flex items-center gap-1"><Info className="h-3.5 w-3.5" /> Grade thresholds (score): {Object.entries((data as AccessoriesResponse).scoreRange || {}).map(([g, v]) => `${g}=${v}`).join(" · ")}</span>
            <span>Grades: {Object.entries((data as AccessoriesResponse).grades || {}).map(([g, l]) => `${g}=${l}`).join(" · ")}</span>
          </div>
          {!data.accessories?.length && <Card><CardContent className="py-16 text-center text-muted-foreground">No accessories owned.</CardContent></Card>}
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {((data as AccessoriesResponse).accessories || []).map((a, i) => (
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
                    {(a.subStats || []).map((s, j) => (
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
    </div>
  )
}
