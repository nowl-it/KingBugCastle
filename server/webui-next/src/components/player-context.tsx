"use client"

import React, { createContext, useContext, useState } from "react"
import { usePlayers } from "@/lib/api"

interface PlayerContextType {
  selectedId: string | null
  setSelectedId: (id: string | null) => void
  activeId: string | null
}

const PlayerContext = createContext<PlayerContextType | undefined>(undefined)

type PlayerSummary = { id: string; name: string; active?: boolean }

export function PlayerProvider({ children }: { children: React.ReactNode }) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const { data } = usePlayers()
  const players = Array.isArray(data) ? data as PlayerSummary[] : []

  const activeId = players.find((p) => p.active)?.id || null
  const effectiveSelectedId = selectedId || activeId

  return (
    <PlayerContext.Provider value={{ selectedId: effectiveSelectedId, setSelectedId, activeId }}>
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
  const { data } = usePlayers()
  const players = Array.isArray(data) ? data as PlayerSummary[] : []
  const { selectedId, setSelectedId } = usePlayerSelection()

  if (!players.length) return null

  return (
    <div className="flex flex-col gap-3 border-b border-border pb-4 mb-6 sm:flex-row sm:items-center sm:gap-4">
      <span className="text-sm font-medium text-muted-foreground">Active Target:</span>
      <select
        className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 sm:w-[300px]"
        value={selectedId || ""}
        onChange={(e) => setSelectedId(e.target.value)}
      >
        <option value="" disabled>Select a player...</option>
        {players.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name} {p.active ? '(ACTIVE)' : ''} - {p.id}
          </option>
        ))}
      </select>
    </div>
  )
}
