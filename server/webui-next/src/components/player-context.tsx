"use client"

import React, { createContext, useContext, useState, useEffect } from "react"
import { usePlayers } from "@/lib/api"

interface PlayerContextType {
  selectedId: string | null
  setSelectedId: (id: string | null) => void
  activeId: string | null
}

const PlayerContext = createContext<PlayerContextType | undefined>(undefined)

export function PlayerProvider({ children }: { children: React.ReactNode }) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const { data: players } = usePlayers()

  const activeId = players?.find((p: any) => p.active)?.id || null

  useEffect(() => {
    if (!selectedId && activeId) {
      setSelectedId(activeId)
    }
  }, [selectedId, activeId])

  return (
    <PlayerContext.Provider value={{ selectedId, setSelectedId, activeId }}>
      {children}
    </PlayerContext.Provider>
  )
}

export function usePlayerSelection() {
  const context = useContext(PlayerContext)
  if (!context) throw new Error("usePlayerSelection must be used within PlayerProvider")
  return context
}

// Shared component for the Player selection bar used in Heroes, Items, etc.
export function PlayerBar() {
  const { data: players } = usePlayers()
  const { selectedId, setSelectedId } = usePlayerSelection()

  if (!players?.length) return null

  return (
    <div className="flex items-center gap-4 border-b border-border pb-4 mb-6">
      <span className="text-sm font-medium text-muted-foreground">Active Target:</span>
      <select 
        className="flex h-10 w-[300px] rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
        value={selectedId || ""}
        onChange={(e) => setSelectedId(e.target.value)}
      >
        <option value="" disabled>Select a player...</option>
        {players.map((p: any) => (
          <option key={p.id} value={p.id}>
            {p.name} {p.active ? '(ACTIVE)' : ''} - {p.id}
          </option>
        ))}
      </select>
    </div>
  )
}
