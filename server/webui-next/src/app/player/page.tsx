"use client"

import { FormEvent, useEffect, useState } from "react"
import Link from "next/link"
import { HandHeart, KeyRound, LogOut, ShieldCheck, Ticket, UserRound } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { PortalMasthead } from "@/components/portal-masthead"
import {
  localizePortalGrant,
  type PortalMessageKey,
  usePortalLocale,
} from "@/components/portal-i18n"
import { RewardedVideoButton } from "@/components/rewarded-video-button"
import { playerFetch } from "@/lib/player-api"

type Player = {
  loginId: string
  uid: string
  name: string
  castleName: string
  authType: "google" | "guest"
}

type TicketWallet = {
  balance: number
  cap: number
  dailyCap: number
  dailyEarned: number
  cooldownLeftSec: number
}

type Grant = {
  type: string
  id: number
  name: string
  minCount: number
  maxCount: number
  note: string
}

type GrantRequest = {
  id: number
  text: string
  itemType: string | null
  itemId: number | null
  status: "pending" | "approved" | "denied"
  created: number
}

type Notice = { key: PortalMessageKey; values?: Record<string, string | number> }
type PortalError = { cause: unknown; fallback: PortalMessageKey }

export default function PlayerPortalPage() {
  const { locale, t, errorMessage } = usePortalLocale()
  const [player, setPlayer] = useState<Player | null>(null)
  const [loading, setLoading] = useState(true)
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [oldPassword, setOldPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [message, setMessage] = useState<Notice | null>(null)
  const [error, setError] = useState<PortalError | null>(null)
  const [busy, setBusy] = useState(false)
  const [ticket, setTicket] = useState<TicketWallet | null>(null)
  const [grants, setGrants] = useState<Grant[]>([])
  const [selectedGrantKey, setSelectedGrantKey] = useState("")
  const [pendingGrant, setPendingGrant] = useState<Grant | null>(null)
  const [requests, setRequests] = useState<GrantRequest[]>([])
  const [requestText, setRequestText] = useState("")
  const [donateInstructions, setDonateInstructions] = useState("")
  const [donateNote, setDonateNote] = useState("")

  const refreshTicket = async () => {
    const result = await playerFetch("/ticket/balance")
    setTicket(result)
  }

  const refreshGrants = async () => {
    const result = await playerFetch("/grant/catalog")
    const entries = result.entries as Grant[]
    setGrants(entries)
    setSelectedGrantKey(current => current || (entries[0] ? `${entries[0].type}:${entries[0].id}` : ""))
  }

  const refreshRequests = async () => {
    const result = await playerFetch("/request/list")
    setRequests(result.entries as GrantRequest[])
  }

  const refreshDonate = async () => {
    const result = await playerFetch("/donate/info")
    setDonateInstructions(String(result.instructions || ""))
  }

  const refresh = async () => {
    const result = await playerFetch("/auth/whoami")
    const nextPlayer = result.player || null
    setPlayer(nextPlayer)
    if (nextPlayer) await Promise.all([refreshTicket(), refreshGrants(), refreshRequests(), refreshDonate()])
    else {
      setTicket(null)
      setGrants([])
      setRequests([])
      setDonateInstructions("")
      setPendingGrant(null)
    }
  }

  useEffect(() => {
    // Initial authentication is an external fetch; its completion owns these local UI states.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh().catch(() => setPlayer(null)).finally(() => setLoading(false))
    // refresh is recreated from local form state; this effect intentionally runs once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const clearFeedback = () => {
    setMessage(null)
    setError(null)
  }

  const loginGuest = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    clearFeedback()
    try {
      const result = await playerFetch("/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      })
      setPlayer(result.player)
      setPassword("")
      await Promise.all([refreshTicket(), refreshGrants(), refreshRequests(), refreshDonate()])
      if (result.mustChangePassword) setMessage({ key: "tempPasswordPrompt" })
    } catch (cause) {
      setError({ cause, fallback: "loginFailed" })
    } finally {
      setBusy(false)
    }
  }

  const logout = async () => {
    await playerFetch("/auth/logout", { method: "POST" })
    setPlayer(null)
    clearFeedback()
  }

  const changePassword = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    clearFeedback()
    try {
      await playerFetch("/auth/password", {
        method: "POST",
        body: JSON.stringify({ oldPassword, newPassword }),
      })
      setPlayer(null)
      setOldPassword("")
      setNewPassword("")
      setMessage({ key: "passwordChanged" })
    } catch (cause) {
      setError({ cause, fallback: "passwordChangeFailed" })
    } finally {
      setBusy(false)
    }
  }

  const grantText = (grant: Grant) => localizePortalGrant(
    locale, grant.type, grant.id, grant.name, grant.note)
  const selectedGrant = grants.find(entry => `${entry.type}:${entry.id}` === selectedGrantKey) || null
  const selectedGrantText = selectedGrant ? grantText(selectedGrant) : null
  const pendingGrantText = pendingGrant ? grantText(pendingGrant) : null

  const redeemGrant = async () => {
    if (!pendingGrant || !pendingGrantText) return
    setBusy(true)
    clearFeedback()
    const reward = `${pendingGrantText.name} ×${pendingGrant.maxCount}`
    try {
      const result = await playerFetch("/grant/self", {
        method: "POST",
        body: JSON.stringify({ type: pendingGrant.type, id: pendingGrant.id, count: pendingGrant.maxCount }),
      })
      setPendingGrant(null)
      setMessage({ key: result.balanceLeft === 0 ? "lastRewardSent" : "rewardSent", values: { reward } })
      await refreshTicket()
    } catch (cause) {
      setError({ cause, fallback: "redeemFailed" })
      await refreshTicket().catch(() => undefined)
    } finally {
      setBusy(false)
    }
  }

  const submitRequest = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    clearFeedback()
    try {
      await playerFetch("/request/submit", { method: "POST", body: JSON.stringify({ text: requestText }) })
      setRequestText("")
      setMessage({ key: "requestSubmitted" })
      await Promise.all([refreshTicket(), refreshRequests()])
    } catch (cause) {
      setError({ cause, fallback: "requestFailed" })
      await refreshTicket().catch(() => undefined)
    } finally {
      setBusy(false)
    }
  }

  const submitDonate = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    clearFeedback()
    try {
      await playerFetch("/donate/note", { method: "POST", body: JSON.stringify({ note: donateNote }) })
      setDonateNote("")
      setMessage({ key: "donationSubmitted" })
    } catch (cause) {
      setError({ cause, fallback: "donationFailed" })
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <main className="portal-loading">{t("loadingLedger")}</main>

  return <main className="portal-page">
    <div className="portal-frame">
      <PortalMasthead title={t("playerLedger")} />

      {message && <p className="portal-notice portal-notice--success" role="status">{t(message.key, message.values)}</p>}
      {error && <p className="portal-notice portal-notice--error" role="alert">{errorMessage(error.cause, error.fallback)}</p>}

      {!player ? <section className="portal-login-grid" aria-label={t("playerAccess")}>
        <article className="portal-welcome">
          <p className="portal-eyebrow">{t("playerAccess")}</p>
          <h2>{t("welcomeLead")}<br /><em>{t("welcomeEmphasis")}</em></h2>
          <p className="portal-copy">{t("welcomeCopy")}</p>
          <div className="portal-rule" />
          <p className="portal-caption">{t("googleRequirement")}</p>
          <Link href="/portal/api/auth/google" prefetch={false} className="portal-button portal-button--gold">
            <ShieldCheck size={17} />{t("continueGoogle")}
          </Link>
        </article>
        <section className="portal-guest-panel">
          <div className="portal-panel-heading">
            <KeyRound size={18} />
            <div><p className="portal-eyebrow">{t("guestAccess")}</p><h2>{t("guestTitle")}</h2></div>
          </div>
          <p className="portal-copy">{t("guestCopy")}</p>
          <form className="portal-form" onSubmit={loginGuest}>
            <label>{t("username")}<Input className="portal-input" value={username} onChange={event => setUsername(event.target.value)} autoComplete="username" required /></label>
            <label>{t("password")}<Input className="portal-input" value={password} onChange={event => setPassword(event.target.value)} autoComplete="current-password" type="password" required /></label>
            <Button className="portal-button portal-button--ink" disabled={busy}>{busy ? t("openingLedger") : t("signIn")}</Button>
          </form>
        </section>
      </section> : <>
        <section className="portal-hero" aria-label={t("linkedPlayerAria")}>
          <div className="portal-player">
            <div className="portal-avatar"><UserRound size={24} /></div>
            <div>
              <p className="portal-eyebrow">{t("linkedPlayer")}</p>
              <h2>{player.name}</h2>
              <p>{player.castleName || "King Bug Castle"} <span>·</span> <code>{player.loginId}</code></p>
            </div>
          </div>
          <Button variant="ghost" size="sm" className="portal-signout" onClick={logout}><LogOut size={15} />{t("signOut")}</Button>
        </section>

        <section className="portal-workspace">
          <article className="portal-ticket-panel">
            <div>
              <p className="portal-eyebrow">{t("ticketReserve")}</p>
              <h2>{t("ticketTitle")}</h2>
              <p className="portal-copy">{t("ticketCopy")}</p>
            </div>
            <div className="portal-ticket-stamp"><Ticket size={21} /><div>{ticket
              ? <><strong>{ticket.balance}</strong><span>/ {ticket.cap} {t("ticketUnit")}</span></>
              : <span>{t("ticketLoading")}</span>}
            </div></div>
            {ticket && <div className="portal-ticket-meta">
              <span>{t("today")} <b>{ticket.dailyEarned} / {ticket.dailyCap}</b></span>
              <Button variant="ghost" size="sm" className="portal-refresh" onClick={() => refreshTicket().catch(cause => setError({ cause, fallback: "ticketRefreshFailed" }))}>{t("refresh")}</Button>
            </div>}
            {ticket?.cooldownLeftSec ? <p className="portal-cooldown">{t("cooldown", { minutes: Math.ceil(ticket.cooldownLeftSec / 60) })}</p> : null}
            <RewardedVideoButton />
          </article>

          <article className="portal-reward-panel">
            <p className="portal-eyebrow">{t("claimEyebrow")}</p>
            <h2>{t("claimTitle")}</h2>
            <p className="portal-copy">{t("claimCopy")}</p>
            {selectedGrant && selectedGrantText ? <>
              <label className="portal-select-label">{t("reward")}
                <select value={selectedGrantKey} onChange={event => { setSelectedGrantKey(event.target.value); setPendingGrant(null) }} disabled={busy} className="portal-select">
                  {grants.map(entry => {
                    const copy = grantText(entry)
                    return <option key={`${entry.type}:${entry.id}`} value={`${entry.type}:${entry.id}`}>{copy.name} ×{entry.maxCount}</option>
                  })}
                </select>
              </label>
              <div className="portal-reward-note"><span>01</span><p>{selectedGrantText.note}</p></div>
              {!pendingGrant
                ? <Button className="portal-button portal-button--gold" disabled={busy || !ticket || ticket.balance < 1} onClick={() => setPendingGrant(selectedGrant)}>{t("useTicket")}</Button>
                : <div className="portal-confirm">
                    <p>{t("confirmReward", { reward: `${pendingGrantText?.name} ×${pendingGrant.maxCount}` })}</p>
                    <div>
                      <Button className="portal-button portal-button--gold" disabled={busy} onClick={redeemGrant}>{busy ? t("sending") : t("confirm")}</Button>
                      <Button variant="ghost" className="portal-cancel" disabled={busy} onClick={() => setPendingGrant(null)}>{t("cancel")}</Button>
                    </div>
                  </div>}
            </> : <p className="portal-empty">{t("catalogLoading")}</p>}
          </article>
        </section>

        <section className="portal-request-panel" aria-labelledby="portal-request-title">
          <div className="portal-request-intro">
            <p className="portal-eyebrow">{t("operatorQueue")}</p>
            <h2 id="portal-request-title">{t("customRequestTitle")}</h2>
            <p className="portal-copy">{t("customRequestCopy")}</p>
          </div>
          <form className="portal-request-form" onSubmit={submitRequest}>
            <label>{t("requestContent")}
              <textarea value={requestText} onChange={event => setRequestText(event.target.value)} maxLength={500} placeholder={t("requestPlaceholder")} required disabled={busy} />
            </label>
            <div className="portal-request-form-footer">
              <span>{t("requestMeta", { count: requestText.length })}</span>
              <Button className="portal-button portal-button--ink" disabled={busy || !ticket || ticket.balance < 1}>{busy ? t("sending") : t("sendRequest")}</Button>
            </div>
          </form>
          <div className="portal-request-history">
            <div className="portal-history-heading">
              <span>{t("recentRequests")}</span>
              <Button variant="ghost" size="sm" className="portal-refresh" onClick={() => refreshRequests().catch(cause => setError({ cause, fallback: "requestRefreshFailed" }))}>{t("refresh")}</Button>
            </div>
            {requests.length ? <ul>{requests.map(request => <li key={request.id}>
              <div><p>{request.text}</p><span>{new Date(request.created * 1000).toLocaleDateString(locale === "vi" ? "vi-VN" : "en-US")}</span></div>
              <b className={`portal-request-status portal-request-status--${request.status}`}>{t(request.status)}</b>
            </li>)}</ul> : <p className="portal-history-empty">{t("noRequests")}</p>}
          </div>
        </section>

        <section className="portal-donate-panel" aria-labelledby="portal-donate-title">
          <div>
            <p className="portal-eyebrow">{t("keepRealm")}</p>
            <h2 id="portal-donate-title">{t("donateTitle")}</h2>
            <p className="portal-copy">{t("donateCopy")}</p>
          </div>
          <div className="portal-donate-body">
            {donateInstructions
              ? <p className="portal-donate-instructions">{donateInstructions}</p>
              : <p className="portal-history-empty">{t("instructionsPending")}</p>}
            <form className="portal-request-form" onSubmit={submitDonate}>
              <label>{t("donationNote")}
                <textarea value={donateNote} onChange={event => setDonateNote(event.target.value)} maxLength={1000} placeholder={t("donationPlaceholder")} required disabled={busy} />
              </label>
              <div className="portal-request-form-footer">
                <span>{donateNote.length}/1000</span>
                <Button className="portal-button portal-button--gold" disabled={busy || !donateNote.trim()}><HandHeart size={16} />{busy ? t("donationSending") : t("donationAction")}</Button>
              </div>
            </form>
          </div>
        </section>

        {player.authType === "guest" && <section className="portal-password-panel">
          <div>
            <p className="portal-eyebrow">{t("securityNote")}</p>
            <h2>{t("passwordTitle")}</h2>
            <p className="portal-copy">{t("passwordCopy")}</p>
          </div>
          <form className="portal-password-form" onSubmit={changePassword}>
            <Input className="portal-input" value={oldPassword} onChange={event => setOldPassword(event.target.value)} type="password" autoComplete="current-password" placeholder={t("currentPassword")} required />
            <Input className="portal-input" value={newPassword} onChange={event => setNewPassword(event.target.value)} type="password" autoComplete="new-password" minLength={8} placeholder={t("newPassword")} required />
            <Button className="portal-button portal-button--ink" disabled={busy}>{busy ? t("updating") : t("changePassword")}</Button>
          </form>
        </section>}
      </>}
    </div>
  </main>
}
