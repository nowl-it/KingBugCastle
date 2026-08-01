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

export default function ItemsPage() {
  const { selectedId } = usePlayerSelection()
  const { data: player, mutate: mutatePlayer } = usePlayer(selectedId || undefined)
  const { data: catalog } = useCatalog()

  const [searchTerm, setSearchTerm] = useState("")
  const [editingItem, setEditingItem] = useState<string | null>(null)
  const [editJson, setEditJson] = useState("")
  const [quantityInput, setQuantityInput] = useState<Record<string, number>>({})

  if (!selectedId) return <div className="p-8"><PlayerBar /></div>

  const items = player?.items || []
  const catalogItems = catalog?.items || []

  // Items can have duplicates or be updated by qty, but based on API `/give_item`, we just send id and qty.
  // The catalog is filtered by name.
  
  const filteredCatalog = catalogItems.filter((i: any) => 
    i.id.toLowerCase().includes(searchTerm.toLowerCase()) || 
    (i.name && i.name.toLowerCase().includes(searchTerm.toLowerCase()))
  )

  const handleGive = async (id: string) => {
    const qty = quantityInput[id] || 1
    await runMutation(`/api/player/${encodeURIComponent(selectedId)}/give_item`, {
      method: 'POST',
      body: JSON.stringify({ item_id: id, count: qty })
    }, `Gave ${qty} of ${id}`)
    mutatePlayer()
  }

  const handleRemove = async (id: string) => {
    if (!confirm("Remove this item?")) return
    await runMutation(`/api/player/${encodeURIComponent(selectedId)}/remove_item`, {
      method: 'POST',
      body: JSON.stringify({ item_id: id })
    }, "Item removed")
    mutatePlayer()
  }

  const handleStartEdit = (item: any) => {
    setEditJson(JSON.stringify(item, null, 2))
    setEditingItem(item.id)
  }

  const handleSaveEdit = async () => {
    try {
      const parsed = JSON.parse(editJson)
      await runMutation(`/api/player/${encodeURIComponent(selectedId)}/update_item`, {
        method: 'POST',
        body: JSON.stringify(parsed)
      }, "Item updated")
      setEditingItem(null)
      mutatePlayer()
    } catch (e: any) {
      alert("Invalid JSON: " + e.message)
    }
  }

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)]">
      <PlayerBar />

      <div className="flex gap-6 flex-1 min-h-0">
        <Card className="flex flex-col w-[450px] shadow-sm">
          <CardHeader className="border-b px-4 py-3">
            <CardTitle className="text-lg">Item Catalog</CardTitle>
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
                {filteredCatalog.map((i: any) => (
                  <TableRow key={i.id}>
                    <TableCell className="font-medium">
                      {i.name || i.id}
                      {i.name && <div className="text-xs font-mono text-muted-foreground">{i.id}</div>}
                    </TableCell>
                    <TableCell className="text-right w-[160px]">
                      <div className="flex items-center gap-2">
                        <Input 
                          type="number" 
                          className="w-16 h-8 px-2 text-sm" 
                          min={1} 
                          value={quantityInput[i.id] || 1} 
                          onChange={(e) => setQuantityInput({...quantityInput, [i.id]: parseInt(e.target.value) || 1})}
                        />
                        <Button size="sm" variant="secondary" onClick={() => handleGive(i.id)} className="h-8">
                          <Plus className="w-4 h-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
                {filteredCatalog.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={2} className="text-center text-muted-foreground py-8">
                      No items match your search.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </Card>

        <Card className="flex flex-col flex-1 shadow-sm">
          <CardHeader className="border-b px-4 py-3 flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-lg">Inventory ({items.length})</CardTitle>
          </CardHeader>
          <div className="flex-1 overflow-auto">
            <Table>
              <TableHeader className="sticky top-0 bg-background/95 backdrop-blur z-10">
                <TableRow>
                  <TableHead>Item</TableHead>
                  <TableHead>Quantity</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((it: any) => {
                  const cat = catalogItems.find((u: any) => u.id === it.id)
                  const name = cat?.name || it.id
                  const isEditing = editingItem === it.id

                  if (isEditing) {
                    return (
                      <TableRow key={it.id} className="bg-muted/30">
                        <TableCell colSpan={3} className="p-4">
                          <div className="flex flex-col gap-3">
                            <div className="flex items-center justify-between">
                              <span className="font-medium">Editing: {name}</span>
                              <div className="flex gap-2">
                                <Button size="sm" variant="ghost" onClick={() => setEditingItem(null)}>Cancel</Button>
                                <Button size="sm" onClick={handleSaveEdit} className="gap-2"><Save className="w-4 h-4" /> Save</Button>
                              </div>
                            </div>
                            <Textarea 
                              value={editJson} 
                              onChange={e => setEditJson(e.target.value)} 
                              className="font-mono text-xs h-[150px]"
                            />
                          </div>
                        </TableCell>
                      </TableRow>
                    )
                  }

                  return (
                    <TableRow key={it.id}>
                      <TableCell>
                        <div className="font-medium">{name}</div>
                        <div className="text-xs font-mono text-muted-foreground">{it.id}</div>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="font-mono text-sm">{it.count}</Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          <Button size="icon" variant="ghost" onClick={() => handleStartEdit(it)}>
                            <Edit2 className="w-4 h-4" />
                          </Button>
                          <Button size="icon" variant="ghost" onClick={() => handleRemove(it.id)} className="text-destructive hover:text-destructive hover:bg-destructive/10">
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
                {items.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={3} className="text-center text-muted-foreground py-12">
                      Inventory is empty.
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
