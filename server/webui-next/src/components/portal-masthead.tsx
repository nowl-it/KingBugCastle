"use client"

import Link from "next/link"
import { ArrowLeft } from "lucide-react"
import { PortalLanguageSwitch, usePortalLocale } from "@/components/portal-i18n"

export function PortalMasthead({ title, backHref, backLabel }: {
  title: string
  backHref?: string
  backLabel?: string
}) {
  const { t } = usePortalLocale()

  return <header className="portal-masthead">
    <div className="portal-brand-copy">
      <p className="portal-eyebrow">{t("brandTagline")}</p>
      <h1>{title}</h1>
    </div>
    <div className="portal-masthead-actions">
      {backHref
        ? <Link href={backHref} className="portal-back-link"><ArrowLeft size={14} />{backLabel}</Link>
        : <span className="portal-status">{t("online")}</span>}
      <PortalLanguageSwitch />
    </div>
  </header>
}
