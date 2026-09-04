import type { Metadata } from "next";
import "./globals.css";
import { ToastProvider } from "@/components/toast-provider";
import { Providers } from "@/app/providers";
import { SiteShell } from "@/components/site-shell";

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
      <body className="min-h-full flex flex-col font-sans">
        <Providers>
          <ToastProvider>
            <SiteShell>{children}</SiteShell>
          </ToastProvider>
        </Providers>
      </body>
    </html>
  );
}
