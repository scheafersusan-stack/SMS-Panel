"use client";

import { useEffect, useState, type ReactNode } from "react";
import { restoreTheme, toggleTheme } from "@/lib/theme";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

export function Shell({ role, route, children }: { role: "user" | "admin"; route: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  useEffect(() => restoreTheme(), []);
  return (
    <div className={`app${open ? " nav-open" : ""}`} id="shell">
      <Sidebar role={role} route={route} onNavigate={() => setOpen(false)} />
      <div className="scrim-mobile" onClick={() => setOpen(false)} aria-hidden="true" />
      <div className="main">
        <Topbar role={role} onMenu={() => setOpen(true)} onTheme={() => toggleTheme()} />
        <main className="content" id="content">
          {children}
        </main>
      </div>
    </div>
  );
}
