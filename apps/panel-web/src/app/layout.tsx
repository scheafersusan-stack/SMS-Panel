import "@fontsource-variable/vazirmatn";
import "@/styles/tokens.css";
import "@/styles/bundle.css";
import "@/styles/app.css";
import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "پیامک‌یار",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

// The pre-paint theme script is a static file (public/theme-init.js) so CSP needs no hash for it.

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="fa" dir="rtl" suppressHydrationWarning>
      <head>
        {/* Intentionally synchronous: must run before first paint to avoid a theme flash. */}
        {/* eslint-disable-next-line @next/next/no-sync-scripts */}
        <script src="/theme-init.js" />
      </head>
      <body>{children}</body>
    </html>
  );
}
