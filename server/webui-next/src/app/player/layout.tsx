import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "Player Dashboard | King Bug Castle",
  description: "Player access, ticket rewards, requests, and server support for King Bug Castle.",
}

export default function PlayerLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return children
}
