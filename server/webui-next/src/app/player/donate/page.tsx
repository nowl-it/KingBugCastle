"use client"

import { FormEvent, useEffect, useState } from "react"
import Link from "next/link"
import { HandHeart } from "lucide-react"
import { Button } from "@/components/ui/button"
import { PortalMasthead } from "@/components/portal-masthead"
import { type PortalMessageKey, usePortalLocale } from "@/components/portal-i18n"
import { playerFetch } from "@/lib/player-api"

type PortalError = { cause: unknown; fallback: PortalMessageKey }

export default function DonatePage() {
  const { t, errorMessage } = usePortalLocale()
  const [ready, setReady] = useState(false)
  const [signedIn, setSignedIn] = useState(false)
  const [instructions, setInstructions] = useState("")
  const [note, setNote] = useState("")
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(false)
  const [error, setError] = useState<PortalError | null>(null)

  useEffect(() => {
    playerFetch("/auth/whoami").then(async result => {
      const active = Boolean(result.authenticated)
      setSignedIn(active)
      if (active) {
        const info = await playerFetch("/donate/info")
        setInstructions(String(info.instructions || ""))
      }
    }).catch(() => setSignedIn(false)).finally(() => setReady(true))
  }, [])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setMessage(false)
    try {
      await playerFetch("/donate/note", { method: "POST", body: JSON.stringify({ note }) })
      setNote("")
      setMessage(true)
    } catch (cause) {
      setError({ cause, fallback: "donationFailed" })
    } finally {
      setBusy(false)
    }
  }

  if (!ready) return <main className="portal-loading">{t("loadingDonate")}</main>

  return <main className="portal-page">
    <div className="portal-frame">
      <PortalMasthead title={t("patronDesk")} backHref="/player" backLabel={t("backLedger")} />
      {!signedIn ? <section className="portal-donate-page">
        <p className="portal-eyebrow">{t("playerAccessRequired")}</p>
        <h2>{t("loginBeforeDonate")}</h2>
        <p className="portal-copy">{t("loginBeforeDonateCopy")}</p>
        <Link href="/player" className="portal-button portal-button--gold">{t("openDashboard")}</Link>
      </section> : <section className="portal-donate-page">
        <p className="portal-eyebrow">{t("keepRealm")}</p>
        <h2>{t("donateTitle")}</h2>
        <p className="portal-copy">{t("donatePageCopy")}</p>
        {instructions
          ? <p className="portal-donate-instructions">{instructions}</p>
          : <p className="portal-history-empty">{t("instructionsPending")}</p>}
        <form className="portal-request-form" onSubmit={submit}>
          <label>{t("donationNote")}
            <textarea value={note} onChange={event => setNote(event.target.value)} maxLength={1000} placeholder={t("donationPlaceholder")} required disabled={busy} />
          </label>
          <div className="portal-request-form-footer">
            <span>{note.length}/1000</span>
            <Button className="portal-button portal-button--gold" disabled={busy || !note.trim()}><HandHeart size={16} />{busy ? t("donationSending") : t("donationAction")}</Button>
          </div>
        </form>
        {message && <p className="portal-notice portal-notice--success" role="status">{t("donationPageSubmitted")}</p>}
        {error && <p className="portal-notice portal-notice--error" role="alert">{errorMessage(error.cause, error.fallback)}</p>}
      </section>}
    </div>
  </main>
}
