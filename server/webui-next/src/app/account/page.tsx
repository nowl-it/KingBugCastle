"use client"

import { useState } from "react"
import { useAdmins, useWhoAmI, runMutation } from "@/lib/api"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { UserPlus, Trash2, ShieldCheck, KeyRound } from "lucide-react"

export default function AccountPage() {
  const { data: who, mutate: mutateWho } = useWhoAmI()
  const { data: admins, mutate: mutateAdmins } = useAdmins()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [oldPassword, setOldPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")

  const change = async () => {
    if (newPassword.length < 8) {
      window.dispatchEvent(new CustomEvent("kgc:toast", { detail: { message: "New password must be at least 8 characters", type: "error" } }))
      return
    }
    await runMutation("/api/auth/password", { method: "POST", body: JSON.stringify({ oldPassword, newPassword }) }, "Password changed")
    setOldPassword(""); setNewPassword("")
  }

  const create = async () => {
    if (username.trim().length < 2) return
    if (password.length < 8) {
      window.dispatchEvent(new CustomEvent("kgc:toast", { detail: { message: "Password must be at least 8 characters", type: "error" } }))
      return
    }
    await runMutation("/api/auth/admins", { method: "POST", body: JSON.stringify({ username: username.trim(), password }) }, "Admin created")
    setUsername(""); setPassword("")
    mutateAdmins(); mutateWho()
  }

  const remove = async (name: string) => {
    if (!window.confirm(`Delete admin account "${name}"?`)) return
    await runMutation(`/api/auth/admins/${encodeURIComponent(name)}`, { method: "DELETE" }, "Admin deleted")
    mutateAdmins(); mutateWho()
  }

  const list = admins?.admins || []

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Account Settings</h1>
        <p className="text-muted-foreground">Admin accounts for dashboard sign-in.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Session</CardTitle>
          <CardDescription>How the current browser is authenticated.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3 text-sm">
          <Badge variant="secondary"><ShieldCheck className="h-3.5 w-3.5 mr-1" /> {who?.authenticated ? "authenticated" : "not authenticated"}</Badge>
          {who?.user && <span className="text-muted-foreground">signed in as <span className="font-medium text-foreground">{who.user}</span></span>}
          <span className="text-muted-foreground">admins configured: {who?.hasAdmins ? "yes" : "no"}</span>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2"><KeyRound className="h-4 w-4" /> Change password</CardTitle>
          <CardDescription>For the account you are signed in as. Other sessions are revoked; this one stays.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="flex-1 space-y-1">
            <label className="text-xs text-muted-foreground">Current password</label>
            <Input type="password" value={oldPassword} onChange={(e) => setOldPassword(e.target.value)} placeholder="••••••••" />
          </div>
          <div className="flex-1 space-y-1">
            <label className="text-xs text-muted-foreground">New password</label>
            <Input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} placeholder="••••••••" />
          </div>
          <Button onClick={change} disabled={oldPassword.length < 1 || newPassword.length < 8}>Change</Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2"><UserPlus className="h-4 w-4" /> Create admin</CardTitle>
          <CardDescription>Minimum 8-character password. Once at least one admin exists, remote sign-in is required.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="flex-1 space-y-1">
            <label className="text-xs text-muted-foreground">Username</label>
            <Input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="admin" />
          </div>
          <div className="flex-1 space-y-1">
            <label className="text-xs text-muted-foreground">Password</label>
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
          </div>
          <Button onClick={create} disabled={!username.trim() || password.length < 8}>Create</Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">Admins ({list.length})</CardTitle></CardHeader>
        <CardContent className="p-0">
          <ul className="divide-y divide-border">
            {list.map((a: any) => (
              <li key={a.username} className="flex items-center justify-between px-4 py-3">
                <div>
                  <span className="text-sm font-medium">{a.username}</span>
                  {who?.user === a.username && <Badge variant="secondary" className="ml-2 text-[10px]">you</Badge>}
                  <div className="text-xs text-muted-foreground font-mono">{a.created ? new Date(a.created * 1000).toLocaleString() : ""}</div>
                </div>
                <Button variant="ghost" size="sm" className="text-destructive" onClick={() => remove(a.username)}><Trash2 className="h-3.5 w-3.5 mr-1" /> Delete</Button>
              </li>
            ))}
            {!list.length && <p className="px-4 py-8 text-sm text-muted-foreground">No admin accounts — dashboard is token/loopback-only.</p>}
          </ul>
        </CardContent>
      </Card>
    </div>
  )
}
