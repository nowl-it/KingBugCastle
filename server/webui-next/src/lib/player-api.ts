export async function playerFetch(path: string, init?: RequestInit) {
  const headers = new Headers(init?.headers)
  if (init?.body) headers.set("Content-Type", "application/json")
  const response = await fetch(`/portal/api${path}`, { ...init, headers })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = body.detail
    const message = typeof detail === "string"
      ? detail
      : typeof detail?.code === "string"
        ? detail.code
        : typeof body.error === "string" ? body.error : "Request failed"
    throw new Error(message)
  }
  return body
}
