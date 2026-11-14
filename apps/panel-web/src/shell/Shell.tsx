"use client";

import { useEffect, useState, type ReactNode } from "react";
import { currentTheme, toggleTheme } from "@/lib/theme";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

export function Shell({ role, route, onLogout, children }: { role: "user" | "admin"; route: string; onLogout?: () => void; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [dark, setDark] = useState(false);
  useEffect(() => setDark(currentTheme() === "dark"), []); // eslint-disable-line react-hooks/set-state-in-effect

  // Drawer: focus moves into it on open; Escape closes it and returns focus to the menu button.
  useEffect(() => {
    if (!open) return;
    document.querySelector<HTMLElement>("#main-nav a")?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      setOpen(false);
      document.getElementById("menu-btn")?.focus();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className={`app${open ? " nav-open" : ""}`} id="shell">
      <Sidebar role={role} route={route} onNavigate={() => setOpen(false)} onLogout={onLogout} />
      <div className="scrim-mobile" onClick={() => setOpen(false)} aria-hidden="true" />
      <div className="main">
        <Topbar
          role={role}
          open={open}
          dark={dark}
          onMenu={() => setOpen(true)}
          onTheme={() => setDark(toggleTheme() === "dark")}
        />
        <main className="content" id="content">
          {children}
        </main>
      </div>
    </div>
  );
}
