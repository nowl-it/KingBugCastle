import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AuthGate } from "@/components/auth-gate";
import { ToastProvider } from "@/components/toast-provider";
import { PlayerProvider } from "@/components/player-context";
import { AppShell } from "@/components/shell";
import { Providers } from "@/app/providers";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "KGC Admin Dashboard",
  description: "Administrative interface for KGC private server",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased dark">
      <body className={`${inter.className} min-h-full flex flex-col`}>
        <Providers>
          <ToastProvider>
            <AuthGate>
              <PlayerProvider>
                <AppShell>{children}</AppShell>
              </PlayerProvider>
            </AuthGate>
          </ToastProvider>
        </Providers>
      </body>
    </html>
  );
}
