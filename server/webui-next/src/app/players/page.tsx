"use client"

import { useState } from "react"
import { usePlayers, usePlayer, runMutation } from "@/lib/api"
import { usePlayerSelection } from "@/components/player-context"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { CheckCircle2, Save, Trash2, Users } from "lucide-react"

export default function PlayersPage() {
  const { data: players, mutate: mutateList } = usePlayers()
  const { selectedId, setSelectedId } = usePlayerSelection()
  const { data: player, mutate: mutatePlayer } = usePlayer(selectedId || undefined)
  const [editingRaw, setEditingRaw] = useState(false)
  const [rawJson, setRawJson] = useState("")

  const handleSelect = (id: string) => {
    setSelectedId(id)
    setEditingRaw(false)
  }

  const handleEditRaw = () => {
    setRawJson(JSON.stringify(player, null, 2))
    setEditingRaw(true)
  }

  const handleSaveRaw = async () => {
    try {
      const parsed = JSON.parse(rawJson)
      await runMutation(`/api/player/${encodeURIComponent(selectedId!)}`, {
        method: 'POST',
        body: JSON.stringify(parsed)
      }, "Player data saved successfully")
      setEditingRaw(false)
      mutatePlayer()
    } catch (e: any) {
      alert("Invalid JSON: " + e.message)
    }
  }

  const handleSetActive = async (id: string) => {
    await runMutation(`/api/player/${encodeURIComponent(id)}/active`, { method: 'POST' }, "Active player set")
    mutateList()
  }

  return (
    <div className="flex h-[calc(100vh-8rem)] gap-6">
      {/* Sidebar: List of Players */}
      <Card className="flex w-[400px] flex-col shadow-sm">
        <CardHeader className="border-b px-4 py-3">
          <CardTitle className="flex items-center gap-2 text-lg">
            <Users className="h-5 w-5" /> Registered Profiles
          </CardTitle>
        </CardHeader>
        <div className="flex-1 overflow-auto">
          <Table>
            <TableHeader className="sticky top-0 bg-background/95 backdrop-blur">
              <TableRow>
                <TableHead>Account</TableHead>
                <TableHead className="w-24 text-right">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {players?.map((p: any) => (
                <TableRow 
                  key={p.id} 
                  className={`cursor-pointer ${selectedId === p.id ? 'bg-muted' : ''}`}
                  onClick={() => handleSelect(p.id)}
                >
                  <TableCell>
                    <div className="font-medium">{p.name || 'Unnamed'}</div>
                    <div className="text-xs text-muted-foreground font-mono truncate max-w-[200px]">{p.id}</div>
                  </TableCell>
                  <TableCell className="text-right">
                    {p.active ? (
                      <Badge variant="default" className="bg-green-500/10 text-green-500 hover:bg-green-500/20 border-green-500/20">ACTIVE</Badge>
                    ) : (
                      <Button variant="outline" size="sm" className="h-7 text-xs" onClick={(e) => { e.stopPropagation(); handleSetActive(p.id) }}>
                        Set Active
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </Card>

      {/* Main Content: Player Details */}
      <div className="flex-1 overflow-y-auto">
        {selectedId ? (
          player ? (
            <Card className="h-full flex flex-col shadow-sm">
              <CardHeader className="border-b px-6 py-4 flex flex-row items-center justify-between">
                <div>
                  <CardTitle className="text-2xl flex items-center gap-3">
                    {player.name || "Unnamed Profile"}
                    {players?.find((p: any) => p.id === selectedId)?.active && (
                      <Badge className="bg-green-500/10 text-green-500 border-green-500/20 hover:bg-green-500/20 text-xs">
                        <CheckCircle2 className="w-3 h-3 mr-1" /> Active Profile
                      </Badge>
                    )}
                  </CardTitle>
                  <div className="text-sm font-mono text-muted-foreground mt-1">{player.id}</div>
                </div>
                <div className="flex items-center gap-2">
                  {!editingRaw ? (
                    <Button variant="outline" onClick={handleEditRaw}>Edit Raw JSON</Button>
                  ) : (
                    <>
                      <Button variant="ghost" onClick={() => setEditingRaw(false)}>Cancel</Button>
                      <Button onClick={handleSaveRaw} className="gap-2"><Save className="w-4 h-4" /> Save Changes</Button>
                    </>
                  )}
                </div>
              </CardHeader>
              <CardContent className="flex-1 p-0 overflow-hidden">
                {editingRaw ? (
                  <Textarea 
                    className="w-full h-full min-h-[500px] font-mono text-sm border-0 rounded-none resize-none focus-visible:ring-0 p-6" 
                    value={rawJson} 
                    onChange={e => setRawJson(e.target.value)} 
                    spellCheck={false}
                  />
                ) : (
                  <div className="p-6">
                    <pre className="bg-muted/50 p-6 rounded-lg overflow-auto max-h-[600px] text-xs font-mono border border-border/50 shadow-inner">
                      {JSON.stringify(player, null, 2)}
                    </pre>
                  </div>
                )}
              </CardContent>
            </Card>
          ) : (
            <div className="flex h-full items-center justify-center text-muted-foreground">Loading profile data...</div>
          )
        ) : (
          <div className="flex h-full items-center justify-center text-muted-foreground border-2 border-dashed border-border rounded-lg bg-muted/5">
            Select a player from the list to view details
          </div>
        )}
      </div>
    </div>
  )
}
