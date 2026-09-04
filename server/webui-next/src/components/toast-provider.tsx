"use client"

import { useState, useEffect } from "react"
import { X } from "lucide-react"

type ToastType = "success" | "error" | "info"

interface Toast {
  id: string
  message: string
  type: ToastType
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  useEffect(() => {
    const handleToast = (e: Event) => {
      const detail = (e as CustomEvent<{ message?: string; type?: ToastType }>).detail
      const { message = 'Notice', type = 'info' } = detail || {}
      const id = Math.random().toString(36).substring(7)
      setToasts(prev => [...prev, { id, message, type }])
      setTimeout(() => {
        setToasts(prev => prev.filter(t => t.id !== id))
      }, 5000)
    }

    window.addEventListener("kgc:toast", handleToast)
    return () => window.removeEventListener("kgc:toast", handleToast)
  }, [])

  return (
    <>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
        {toasts.map(t => (
          <div 
            key={t.id} 
            className={`flex items-center gap-3 rounded-lg border bg-card p-4 shadow-lg min-w-[300px] transition-all ${
              t.type === 'success' ? 'border-l-4 border-l-green-500' :
              t.type === 'error' ? 'border-l-4 border-l-red-500' :
              'border-l-4 border-l-blue-500'
            }`}
          >
            <div className="flex-1 text-sm font-medium">{t.message}</div>
            <button onClick={() => setToasts(prev => prev.filter(x => x.id !== t.id))} className="text-muted-foreground hover:text-foreground">
              <X size={16} />
            </button>
          </div>
        ))}
      </div>
    </>
  )
}
