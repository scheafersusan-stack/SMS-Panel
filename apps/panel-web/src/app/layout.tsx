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

// Applies the stored theme before first paint (no flash); storage may be blocked.
const THEME_SCRIPT =
  'try{var t=localStorage.getItem("pk_theme");if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}catch(e){}';

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="fa" dir="rtl" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
