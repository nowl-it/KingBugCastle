"use client"

import { Button } from "@/components/ui/button"
import { usePortalLocale } from "@/components/portal-i18n"

export function RewardedVideoButton() {
  const { t } = usePortalLocale()
  return <Button className="portal-button portal-button--gold" disabled>
    {t("videoDisabled")}
  </Button>
}
