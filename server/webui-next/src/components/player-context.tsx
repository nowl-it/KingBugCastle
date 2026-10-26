"use client"

import React, { createContext, useContext, useEffect, useMemo, useRef, useState } from "react"
import { Check, ChevronDown, Search, UserRound, X } from "lucide-react"
import { usePlayers } from "@/lib/api"
import { Badge } from "@/components/ui/badge"

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
// A searchable combobox: the old native <select> buried long ids in one-line
// options with no way to filter, so we render a dropdown panel with its own
// search field over name / id / clan.
export function PlayerBar() {
  const { data } = usePlayers()
  const players = useMemo(
    () => (Array.isArray(data) ? data as PlayerSummary[] : []),
    [data],
  )
  const { selectedId, setSelectedId, activeId } = usePlayerSelection()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const wrapRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)

  const selected = players.find((p) => p.id === selectedId)

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return players
    return players.filter(
      (p) => p.name.toLowerCase().includes(q) || p.id.toLowerCase().includes(q),
    )
  }, [players, query])

  useEffect(() => {
    if (!open) return
    const onDocClick = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false)
    }
    document.addEventListener("mousedown", onDocClick)
    document.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("mousedown", onDocClick)
      document.removeEventListener("keydown", onKey)
    }
  }, [open])

  useEffect(() => {
    if (open) searchRef.current?.focus()
  }, [open])

  if (!players.length) return null

  return (
    <div className="flex flex-col gap-3 border-b border-border pb-4 mb-6 sm:flex-row sm:items-center sm:gap-4">
      <span className="text-sm font-medium text-muted-foreground">Active Target:</span>
      <div ref={wrapRef} className="relative w-full sm:w-[340px]">
        <button
          type="button"
          aria-haspopup="listbox"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className="flex h-10 w-full items-center gap-2 rounded-md border border-input bg-background px-3 py-2 text-sm shadow-xs ring-offset-background transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          {selected ? (
            <>
              <span className={`h-2 w-2 shrink-0 rounded-full ${selected.id === activeId ? "bg-emerald-500" : "bg-muted-foreground/40"}`} />
              <span className="truncate font-medium">{selected.name || selected.id}</span>
              <span className="truncate font-mono text-xs text-muted-foreground">{selected.id}</span>
            </>
          ) : (
            <span className="text-muted-foreground">Select a player...</span>
          )}
          <ChevronDown className="ml-auto h-4 w-4 shrink-0 text-muted-foreground" />
        </button>
        {open && (
          <div className="absolute z-50 mt-1 w-full overflow-hidden rounded-md border bg-popover text-popover-foreground shadow-md">
            <div className="flex items-center gap-2 border-b px-3">
              <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
              <input
                ref={searchRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && filtered.length) {
                    setSelectedId(filtered[0].id)
                    setOpen(false)
                  }
                }}
                placeholder="Search by name or id..."
                className="h-9 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
              />
              {query && (
                <button type="button" aria-label="Clear search" onClick={() => setQuery("")} className="text-muted-foreground hover:text-foreground">
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
            <div role="listbox" className="max-h-72 overflow-y-auto py-1">
              {filtered.length === 0 && (
                <div className="px-3 py-6 text-center text-sm text-muted-foreground">
                  No players match &quot;{query}&quot;
                </div>
              )}
              {filtered.map((p) => {
                const isSelected = p.id === selectedId
                return (
                  <button
                    key={p.id}
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    onClick={() => {
                      setSelectedId(p.id)
                      setOpen(false)
                      setQuery("")
                    }}
                    className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-accent hover:text-accent-foreground ${isSelected ? "bg-accent/60 font-medium" : ""}`}
                  >
                    <UserRound className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate">{p.name || p.id}</span>
                    {p.id === activeId && (
                      <Badge variant="success" className="shrink-0">
                        ACTIVE
                      </Badge>
                    )}
                    <span className="shrink-0 font-mono text-xs text-muted-foreground">{p.id}</span>
                    {isSelected && <Check className="h-4 w-4 shrink-0 text-primary" />}
                  </button>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
