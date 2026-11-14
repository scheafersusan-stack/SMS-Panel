export type Theme = "light" | "dark";
const KEY = "pk_theme";

function isTheme(v: unknown): v is Theme {
  return v === "light" || v === "dark";
}

export function readStoredTheme(): Theme | null {
  try {
    const v = window.localStorage.getItem(KEY);
    return isTheme(v) ? v : null;
  } catch {
    return null;
  }
}

export function currentTheme(): Theme {
  const attr = document.documentElement.getAttribute("data-theme");
  if (isTheme(attr)) return attr;
  const dark = typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
  return dark ? "dark" : "light";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
  try {
    window.localStorage.setItem(KEY, theme);
  } catch {
    // private mode or blocked storage: the choice just is not remembered
  }
}

export function restoreTheme(): void {
  const t = readStoredTheme();
  if (t) document.documentElement.setAttribute("data-theme", t);
}

export function toggleTheme(): Theme {
  const next: Theme = currentTheme() === "dark" ? "light" : "dark";
  applyTheme(next);
  return next;
}
