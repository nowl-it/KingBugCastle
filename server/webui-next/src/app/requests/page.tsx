"use client"

import { useMemo, useState } from "react"
import { Check, ChevronDown, Search, Ticket, X } from "lucide-react"
import { runMutation, useCatalog, useGrantRequests } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"

type RequestStatus = "all" | "pending" | "approved" | "denied"

type GrantRequest = {
  id: number
  loginId: string
  uid: string
  text: string
  itemType: string | null
  itemId: number | null
  status: Exclude<RequestStatus, "all">
  created: number
  resolvedAt: number | null
  resolvedBy: string | null
}

const STATUS_LABEL: Record<Exclude<RequestStatus, "all">, string> = {
  pending: "Pending",
  approved: "Approved",
  denied: "Denied",
}

export default function RequestsPage() {
  const [status, setStatus] = useState<RequestStatus>("pending")
  const { data, isLoading, error, mutate } = useGrantRequests(status)
  const { data: catalogData } = useCatalog()
  const [openId, setOpenId] = useState<number | null>(null)
  const [rewardType, setRewardType] = useState("Gold")
  const [rewardId, setRewardId] = useState("")
  const [rewardAmount, setRewardAmount] = useState("1")
  const [search, setSearch] = useState("")
  const [denyReason, setDenyReason] = useState("")
  const [busy, setBusy] = useState(false)

  const requests = (data?.entries || []) as GrantRequest[]
  const grantable = (catalogData?.grantable || []) as string[]
  const catalog = catalogData?.catalog
  const needsId = !["Gold", "Cash", "Heart"].includes(rewardType)
  const rewardList = useMemo(() => (catalog?.[rewardType] || []) as { id: number; name: string }[], [catalog, rewardType])
  const matchingRewards = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (q ? rewardList.filter(reward => String(reward.id).includes(q) || reward.name.toLowerCase().includes(q)) : rewardList).slice(0, 12)
  }, [rewardList, search])

  const beginResolve = (request: GrantRequest) => {
    setOpenId(current => current === request.id ? null : request.id)
    setRewardType("Gold"); setRewardId(""); setRewardAmount("1"); setSearch(""); setDenyReason("")
  }

  const approve = async (request: GrantRequest) => {
    setBusy(true)
    try {
      await runMutation(`/api/requests/${request.id}/approve`, {
        method: "POST",
        body: JSON.stringify({
          rewardType,
          rewardId: needsId ? Number(rewardId) : 0,
          rewardAmount: Number(rewardAmount),
        }),
      }, "Request approved and reward mailed")
      setOpenId(null)
      await mutate()
    } finally {
      setBusy(false)
    }
  }

  const deny = async (request: GrantRequest) => {
    setBusy(true)
    try {
      await runMutation(`/api/requests/${request.id}/deny`, {
        method: "POST", body: JSON.stringify({ reason: denyReason }),
      }, "Request denied; one ticket refunded")
      setOpenId(null)
      await mutate()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Player Requests</h1>
          <p className="text-muted-foreground">Each request has already spent one ticket. Approve with a mail reward, or deny to refund it.</p>
        </div>
        <label className="grid gap-1 text-xs font-medium text-muted-foreground">
          Queue view
          <select value={status} onChange={event => { setStatus(event.target.value as RequestStatus); setOpenId(null) }} className="h-9 rounded-md border border-input bg-background px-3 text-sm text-foreground">
            <option value="pending">Pending</option><option value="approved">Approved</option><option value="denied">Denied</option><option value="all">All history</option>
          </select>
        </label>
      </div>

      {error && <p className="text-sm text-destructive">Could not load requests: {error.message}</p>}
      <div className="grid gap-4">
        {isLoading && <Card><CardContent className="py-8 text-sm text-muted-foreground">Loading queue…</CardContent></Card>}
        {!isLoading && !requests.length && <Card><CardContent className="py-8 text-sm text-muted-foreground">No {status === "all" ? "player requests" : status + " requests"}.</CardContent></Card>}
        {requests.map(request => {
          const isPending = request.status === "pending"
          const expanded = openId === request.id
          return <Card key={request.id} className={expanded ? "border-primary/50" : undefined}>
            <CardHeader className="gap-3 pb-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0 space-y-1">
                <CardTitle className="flex flex-wrap items-center gap-2 text-base"><span>#{request.id}</span><Badge variant={request.status === "pending" ? "secondary" : "outline"}>{STATUS_LABEL[request.status]}</Badge></CardTitle>
                <CardDescription className="font-mono text-[11px]">{request.loginId} · {request.uid} · {new Date(request.created * 1000).toLocaleString()}</CardDescription>
              </div>
              {isPending && <Button size="sm" variant={expanded ? "secondary" : "default"} onClick={() => beginResolve(request)}><ChevronDown className="mr-1 h-3.5 w-3.5" />{expanded ? "Close" : "Review"}</Button>}
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="whitespace-pre-wrap text-sm leading-6">{request.text}</p>
              {(request.itemType || request.itemId !== null) && <p className="text-xs text-muted-foreground">Player asked for: <span className="font-mono">{request.itemType || "unspecified"}{request.itemId !== null ? ` #${request.itemId}` : ""}</span></p>}
              {!isPending && <p className="text-xs text-muted-foreground">Resolved by {request.resolvedBy || "operator"}{request.resolvedAt ? ` · ${new Date(request.resolvedAt * 1000).toLocaleString()}` : ""}</p>}
              {expanded && <section className="grid gap-5 border-t border-border pt-4 lg:grid-cols-2">
                <div className="space-y-3">
                  <div><h2 className="text-sm font-semibold">Approve and send mail</h2><p className="text-xs text-muted-foreground">Choose the exact reward from the admin catalog.</p></div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <label className="grid gap-1 text-xs text-muted-foreground">Reward type
                      <select value={rewardType} onChange={event => { setRewardType(event.target.value); setRewardId(""); setSearch("") }} className="h-9 rounded-md border border-input bg-background px-3 text-sm text-foreground">
                        {grantable.map(type => <option key={type} value={type}>{type}</option>)}
                      </select>
                    </label>
                    <label className="grid gap-1 text-xs text-muted-foreground">Amount<Input type="number" min="1" value={rewardAmount} onChange={event => setRewardAmount(event.target.value)} /></label>
                  </div>
                  {needsId && <>
                    <label className="grid gap-1 text-xs text-muted-foreground">Reward ID<Input type="number" value={rewardId} onChange={event => setRewardId(event.target.value)} placeholder="Catalog ID" /></label>
                    {rewardList.length > 0 && <div className="space-y-2"><div className="relative"><Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" /><Input className="pl-8" value={search} onChange={event => setSearch(event.target.value)} placeholder={`Find ${rewardType}…`} /></div><div className="max-h-36 overflow-y-auto rounded-md border border-border divide-y divide-border">{matchingRewards.map(reward => <button key={reward.id} type="button" onClick={() => setRewardId(String(reward.id))} className={`flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-muted/50 ${String(reward.id) === rewardId ? "bg-muted" : ""}`}><span>{reward.name}</span><span className="font-mono text-xs text-muted-foreground">#{reward.id}</span></button>)}</div></div>}
                  </>}
                  <Button disabled={busy || !rewardAmount || (needsId && !rewardId)} onClick={() => approve(request)}><Check className="mr-1 h-4 w-4" />Approve & mail reward</Button>
                </div>
                <div className="space-y-3 rounded-md border border-destructive/25 bg-destructive/5 p-4">
                  <div><h2 className="text-sm font-semibold">Deny and refund</h2><p className="text-xs text-muted-foreground">The player receives one ticket back, plus an in-game mail.</p></div>
                  <Textarea value={denyReason} onChange={event => setDenyReason(event.target.value)} maxLength={500} placeholder="Optional reason shown in the mail" className="min-h-24" />
                  <Button variant="destructive" disabled={busy} onClick={() => deny(request)}><X className="mr-1 h-4 w-4" />Deny & refund ticket</Button>
                </div>
              </section>}
            </CardContent>
          </Card>
        })}
      </div>
      <p className="flex items-center gap-1 text-xs text-muted-foreground"><Ticket className="h-3.5 w-3.5" /> Ticket deduction/refund and mail delivery are one database transaction.</p>
    </div>
  )
}
