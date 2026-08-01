"use client"

import { useState } from "react"
import { useWhoAmI, runMutation } from "@/lib/api"
import { Card, CardHeader, CardTitle, CardContent, CardDescription, CardFooter } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { UserPlus, ShieldCheck } from "lucide-react"

export default function AccountPage() {
  const { data: who, mutate } = useWhoAmI()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [busy, setBusy] = useState(false)

  const handleCreate = async () => {
    setBusy(true)
    try {
      await runMutation('/api/auth/register', {
        method: 'POST',
        body: JSON.stringify({ username, password })
      }, "Admin account created successfully")
      setUsername("")
      setPassword("")
      mutate()
    } catch (e: any) {
      alert(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Account Settings</h1>
        <p className="text-muted-foreground">Manage administrative access to this dashboard.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><UserPlus className="w-5 h-5" /> Create Admin Account</CardTitle>
          <CardDescription>
            {who?.hasAdmins 
              ? "The system already has an admin. Creating another one adds an additional user."
              : "No admin account exists yet. Create one to lock down the dashboard."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium">Username</label>
            <Input 
              value={username} 
              onChange={e => setUsername(e.target.value)} 
              placeholder="e.g. root" 
            />
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">Password</label>
            <Input 
              type="password" 
              value={password} 
              onChange={e => setPassword(e.target.value)} 
              placeholder="Min 8 characters" 
            />
          </div>
        </CardContent>
        <CardFooter className="border-t px-6 py-4">
          <Button onClick={handleCreate} disabled={busy || !username || !password} className="gap-2">
            <ShieldCheck className="w-4 h-4" /> Create Account
          </Button>
        </CardFooter>
      </Card>
    </div>
  )
}
