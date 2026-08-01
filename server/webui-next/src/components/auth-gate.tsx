"use client"

import { useState, useEffect } from "react"
import { useWhoAmI, runMutation } from "@/lib/api"
import { Card, CardHeader, CardTitle, CardContent } from "./ui/card"
import { Input } from "./ui/input"
import { Button } from "./ui/button"

export function AuthGate({ children }: { children: React.ReactNode }) {
  const { data: who, error, mutate } = useWhoAmI()
  const [tokenInput, setTokenInput] = useState("")
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [busy, setBusy] = useState(false)
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
    const handleUnauthorized = () => {
      mutate()
    }
    window.addEventListener("kgc:unauthorized", handleUnauthorized)
    return () => window.removeEventListener("kgc:unauthorized", handleUnauthorized)
  }, [mutate])

  if (!mounted) return null

  if (error || !who) {
    return <div className="flex h-screen items-center justify-center text-muted-foreground">LOADING_ACCESS_DATA...</div>
  }

  if (who.authenticated) {
    return <>{children}</>
  }

  const applyToken = async () => {
    localStorage.setItem("admin_token", tokenInput.trim())
    await mutate()
  }

  const doLogin = async () => {
    setBusy(true)
    try {
      await runMutation('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password })
      }, "Logged in successfully")
      await mutate()
    } catch (e) {
      // toast is already fired by runMutation
    } finally {
      setBusy(false)
    }
  }

  let gateType = "locked"
  if (who.hasAdmins) gateType = "login"
  else if (who.tokenMode) gateType = "token"

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-muted/30">
      <Card className="w-[420px] shadow-xl">
        <CardHeader>
          <CardTitle>
            {gateType === "token" && "Admin Token Required"}
            {gateType === "login" && "Authentication"}
            {gateType === "locked" && "Access Denied"}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {gateType === "token" && (
            <div className="flex flex-col gap-4">
              <Input 
                type="password" 
                placeholder="Admin Token" 
                value={tokenInput} 
                onChange={e => setTokenInput(e.target.value)} 
                onKeyDown={e => e.key === 'Enter' && applyToken()}
              />
              <Button onClick={applyToken} className="w-full">Unlock Terminal</Button>
            </div>
          )}
          {gateType === "login" && (
            <div className="flex flex-col gap-4">
              <Input 
                type="text" 
                placeholder="Username" 
                value={username} 
                onChange={e => setUsername(e.target.value)} 
                onKeyDown={e => e.key === 'Enter' && doLogin()}
              />
              <Input 
                type="password" 
                placeholder="Password" 
                value={password} 
                onChange={e => setPassword(e.target.value)} 
                onKeyDown={e => e.key === 'Enter' && doLogin()}
              />
              <Button onClick={doLogin} disabled={busy} className="w-full">Access System</Button>
            </div>
          )}
          {gateType === "locked" && (
            <div className="text-destructive font-medium">
              Dashboard is loopback-only. Create an admin account or set KGC_ADMIN_TOKEN.
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
