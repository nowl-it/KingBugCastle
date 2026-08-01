"use client"

import { useState } from "react"
import { usePlayers, runMutation } from "@/lib/api"
import { Card, CardHeader, CardTitle, CardContent, CardDescription, CardFooter } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Send, Globe, User } from "lucide-react"

export default function MailPage() {
  const { data: players } = usePlayers()
  const [recipientType, setRecipientType] = useState<"global" | "targeted">("global")
  const [targetId, setTargetId] = useState("")
  const [title, setTitle] = useState("")
  const [content, setContent] = useState("")
  const [itemJson, setItemJson] = useState("[]")
  const [busy, setBusy] = useState(false)

  const handleSend = async () => {
    setBusy(true)
    try {
      const items = JSON.parse(itemJson)
      const payload = {
        title,
        content,
        items
      }

      if (recipientType === "global") {
        await runMutation('/api/mail/global', {
          method: 'POST',
          body: JSON.stringify(payload)
        }, "Global mail sent")
      } else {
        if (!targetId) throw new Error("Please specify a target player ID")
        await runMutation(`/api/player/${encodeURIComponent(targetId)}/mail`, {
          method: 'POST',
          body: JSON.stringify(payload)
        }, "Targeted mail sent")
      }
      
      setTitle("")
      setContent("")
      setItemJson("[]")
    } catch (e: any) {
      alert(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Mail Dispatch</h1>
        <p className="text-muted-foreground">Send custom mail with attachments to players.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Compose Mail</CardTitle>
          <CardDescription>Items must be a JSON array of `{"{"} item_id, count {"}"}` objects.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="space-y-2">
            <label className="text-sm font-medium">Recipient</label>
            <div className="flex gap-4">
              <Button 
                variant={recipientType === "global" ? "default" : "outline"} 
                onClick={() => setRecipientType("global")}
                className="w-1/2 gap-2"
              >
                <Globe className="w-4 h-4" /> All Active Players
              </Button>
              <Button 
                variant={recipientType === "targeted" ? "default" : "outline"} 
                onClick={() => setRecipientType("targeted")}
                className="w-1/2 gap-2"
              >
                <User className="w-4 h-4" /> Specific Player
              </Button>
            </div>
          </div>

          {recipientType === "targeted" && (
            <div className="space-y-2">
              <label className="text-sm font-medium">Target Player ID</label>
              <select 
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
                value={targetId}
                onChange={e => setTargetId(e.target.value)}
              >
                <option value="" disabled>Select player...</option>
                {players?.map((p: any) => (
                  <option key={p.id} value={p.id}>{p.name} - {p.id}</option>
                ))}
              </select>
            </div>
          )}

          <div className="space-y-2">
            <label className="text-sm font-medium">Title</label>
            <Input value={title} onChange={e => setTitle(e.target.value)} placeholder="Mail Title..." />
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">Content / Message</label>
            <Textarea value={content} onChange={e => setContent(e.target.value)} placeholder="Type your message here..." className="min-h-[100px]" />
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">Attachments (JSON Array)</label>
            <Textarea 
              value={itemJson} 
              onChange={e => setItemJson(e.target.value)} 
              className="font-mono text-xs min-h-[150px]"
              placeholder={`[\n  { "item_id": 1, "count": 100 }\n]`}
            />
          </div>
        </CardContent>
        <CardFooter className="border-t px-6 py-4">
          <Button onClick={handleSend} disabled={busy || !title || !content} className="w-full gap-2 text-lg h-12">
            <Send className="w-5 h-5" /> Send Mail
          </Button>
        </CardFooter>
      </Card>
    </div>
  )
}
