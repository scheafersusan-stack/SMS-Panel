import { useCallback, useEffect, useState } from "react";
import { faDigits } from "./format";

/** «۰۱:۴۵» for a number of seconds. */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return faDigits(`${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`);
}

/** Whole seconds left until a deadline set by `start(seconds)`; 0 when idle or finished. */
export function useCountdown(): { left: number; start: (seconds: number) => void } {
  const [deadline, setDeadline] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (deadline <= Date.now()) return;
    const id = setInterval(() => {
      const t = Date.now();
      setNow(t);
      if (t >= deadline) clearInterval(id);
    }, 250);
    return () => clearInterval(id);
  }, [deadline]);
  const start = useCallback((seconds: number) => {
    const t = Date.now();
    setNow(t);
    setDeadline(t + Math.max(0, seconds) * 1000);
  }, []);
  return { left: Math.max(0, Math.ceil((deadline - now) / 1000)), start };
}
