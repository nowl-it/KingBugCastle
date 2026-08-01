"use client"

import { useState } from "react"
import { usePlayer, useCatalog, runMutation } from "@/lib/api"
import { usePlayerSelection, PlayerBar } from "@/components/player-context"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Textarea } from "@/components/ui/textarea"
import { Search, Save, Trash2, Plus, Edit2 } from "lucide-react"

export default function AccessoriesPage() {
  const { selectedId } = usePlayerSelection()
  const { data: player, mutate: mutatePlayer } = usePlayer(selectedId || undefined)
  const { data: catalog } = useCatalog()

  const [searchTerm, setSearchTerm] = useState("")
  const [editingAcc, setEditingAcc] = useState<string | null>(null)
  const [editJson, setEditJson] = useState("")

  if (!selectedId) return <div className="p-8"><PlayerBar /></div>

  const accessories = player?.accessories || []
  const catalogAccessories = catalog?.accessories || []
  
  const filteredCatalog = catalogAccessories.filter((a: any) => 
    a.id.toLowerCase().includes(searchTerm.toLowerCase()) || 
    (a.name && a.name.toLowerCase().includes(searchTerm.toLowerCase()))
  )

  const handleGive = async (id: string) => {
    await runMutation(`/api/player/${encodeURIComponent(selectedId)}/give_accessory`, {
      method: 'POST',
      body: JSON.stringify({ equip_id: id })
    }, "Accessory granted")
    mutatePlayer()
  }

  const handleRemove = async (sn: number) => {
    if (!confirm("Remove this accessory?")) return
    await runMutation(`/api/player/${encodeURIComponent(selectedId)}/remove_accessory`, {
      method: 'POST',
      body: JSON.stringify({ sn })
    }, "Accessory removed")
    mutatePlayer()
  }

  const handleStartEdit = (acc: any) => {
    setEditJson(JSON.stringify(acc, null, 2))
    setEditingAcc(acc.sn)
  }

  const handleSaveEdit = async () => {
    try {
      const parsed = JSON.parse(editJson)
      await runMutation(`/api/player/${encodeURIComponent(selectedId)}/update_accessory`, {
        method: 'POST',
        body: JSON.stringify(parsed)
      }, "Accessory updated")
      setEditingAcc(null)
      mutatePlayer()
    } catch (e: any) {
      alert("Invalid JSON: " + e.message)
    }
  }

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)]">
      <PlayerBar />

      <div className="flex gap-6 flex-1 min-h-0">
        <Card className="flex flex-col w-1/3 shadow-sm">
          <CardHeader className="border-b px-4 py-3">
            <CardTitle className="text-lg">Accessory Catalog</CardTitle>
            <div className="relative mt-2">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input 
                type="text" 
                placeholder="Search catalog..." 
                className="pl-9"
                value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)}
              />
            </div>
          </CardHeader>
          <div className="flex-1 overflow-auto p-0">
            <Table>
              <TableBody>
                {filteredCatalog.map((a: any) => (
                  <TableRow key={a.id}>
                    <TableCell className="font-medium">
                      {a.name || a.id}
                      {a.name && <div className="text-xs font-mono text-muted-foreground">{a.id}</div>}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button size="sm" variant="secondary" onClick={() => handleGive(a.id)} className="h-8">
                        <Plus className="w-4 h-4 mr-1" /> Give
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {filteredCatalog.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={2} className="text-center text-muted-foreground py-8">
                      No accessories match your search.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </Card>

        <Card className="flex flex-col flex-1 shadow-sm">
          <CardHeader className="border-b px-4 py-3 flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-lg">Owned Accessories ({accessories.length})</CardTitle>
          </CardHeader>
          <div className="flex-1 overflow-auto">
            <Table>
              <TableHeader className="sticky top-0 bg-background/95 backdrop-blur z-10">
                <TableRow>
                  <TableHead>Accessory</TableHead>
                  <TableHead>SN</TableHead>
                  <TableHead>Tier / Level</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {accessories.map((a: any) => {
                  const cat = catalogAccessories.find((u: any) => u.id === a.id)
                  const name = cat?.name || a.id
                  const isEditing = editingAcc === a.sn

                  if (isEditing) {
                    return (
                      <TableRow key={a.sn} className="bg-muted/30">
                        <TableCell colSpan={4} className="p-4">
                          <div className="flex flex-col gap-3">
                            <div className="flex items-center justify-between">
                              <span className="font-medium">Editing: {name} (SN: {a.sn})</span>
                              <div className="flex gap-2">
                                <Button size="sm" variant="ghost" onClick={() => setEditingAcc(null)}>Cancel</Button>
                                <Button size="sm" onClick={handleSaveEdit} className="gap-2"><Save className="w-4 h-4" /> Save</Button>
                              </div>
                            </div>
                            <Textarea 
                              value={editJson} 
                              onChange={e => setEditJson(e.target.value)} 
                              className="font-mono text-xs h-[250px]"
                            />
                          </div>
                        </TableCell>
                      </TableRow>
                    )
                  }

                  return (
                    <TableRow key={a.sn}>
                      <TableCell>
                        <div className="font-medium">{name}</div>
                        <div className="text-xs font-mono text-muted-foreground">{a.id}</div>
                      </TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">{a.sn}</TableCell>
                      <TableCell>
                        <Badge variant="outline" className="mr-2">Tier {a.tier}</Badge>
                        <Badge variant="secondary">Lv {a.level}</Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          <Button size="icon" variant="ghost" onClick={() => handleStartEdit(a)}>
                            <Edit2 className="w-4 h-4" />
                          </Button>
                          <Button size="icon" variant="ghost" onClick={() => handleRemove(a.sn)} className="text-destructive hover:text-destructive hover:bg-destructive/10">
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
                {accessories.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={4} className="text-center text-muted-foreground py-12">
                      This player has no accessories.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </Card>
      </div>
    </div>
  )
}
