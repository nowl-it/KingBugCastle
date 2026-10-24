"use client"

import { PackageOpen } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import type { AccessoriesResponse } from "./types"

export function PlayerInventory({ owned, selectedId }: { owned: AccessoriesResponse | undefined; selectedId: string | null }) {
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <div className="min-w-0">
          <CardTitle className="flex items-center gap-2"><PackageOpen className="h-4 w-4 text-muted-foreground" /> Player inventory</CardTitle>
          <CardDescription>Read-only view of the accessories currently owned by the selected player.</CardDescription>
          {selectedId && owned && (
            <details className="mt-2 text-xs text-muted-foreground">
              <summary className="cursor-pointer font-medium text-foreground">Scoring reference</summary>
              <p className="mt-2 leading-5">Thresholds: {Object.entries(owned.scoreRange || {}).map(([grade, value]) => `${grade} ${value}`).join(" · ") || "none"}<br />Grades: {Object.entries(owned.grades || {}).map(([grade, label]) => `${grade} ${label}`).join(" · ") || "none"}</p>
            </details>
          )}
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {!selectedId ? (
          <div className="grid h-48 place-items-center text-sm text-muted-foreground">Select a player above.</div>
        ) : !owned ? (
          <div className="space-y-2 p-4">{[0, 1, 2].map((item) => <div key={item} className="h-14 animate-pulse rounded-lg bg-muted" />)}</div>
        ) : !owned.accessories?.length ? (
          <div className="grid h-48 place-items-center text-sm text-muted-foreground">This player owns no accessories.</div>
        ) : (
          <div className="max-h-[65vh] overflow-auto">
            <Table className="min-w-[760px]">
              <TableHeader>
                <TableRow>
                  <TableHead>Accessory</TableHead>
                  <TableHead>Main stat</TableHead>
                  <TableHead>Sub-stats</TableHead>
                  <TableHead className="text-right">Score</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {owned.accessories.map((accessory) => (
                  <TableRow key={accessory.id} className="align-top">
                    <TableCell className="py-3">
                      <span className="font-medium">{accessory.typeName} <span className="font-mono font-normal text-muted-foreground">#{accessory.id}</span></span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">{accessory.rarityName} · Lv {accessory.level} · {accessory.synergyName}{accessory.unitName ? ` · ${accessory.unitName}` : ""}</span>
                    </TableCell>
                    <TableCell className="py-3 font-medium">{accessory.mainStatLabel || "—"}</TableCell>
                    <TableCell className="py-3 text-xs text-muted-foreground">{(accessory.subStats || []).map((stat) => `${stat.label} ${stat.score ?? "—"}${stat.grade ? ` (${stat.grade})` : ""}`).join(" · ") || "—"}</TableCell>
                    <TableCell className="py-3 text-right font-mono tnum text-base font-semibold">{accessory.scoreTotal}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
