"use client";

import { useCallback, useState, type ReactNode } from "react";
import { Toast, ToastHost } from "@/ui/Feedback";

interface Item {
  id: number;
  message: string;
  tone: "ok" | "bad";
}

/** Transient confirmations: `toast(message, tone)` and the `host` element to render once. */
export function useToasts(): { toast: (message: string, tone?: "ok" | "bad") => void; host: ReactNode } {
  const [items, setItems] = useState<Item[]>([]);
  const close = useCallback((id: number) => setItems((l) => l.filter((i) => i.id !== id)), []);
  const toast = useCallback(
    (message: string, tone: "ok" | "bad" = "ok") => {
      const id = Date.now() + Math.random();
      setItems((l) => [...l, { id, message, tone }]);
      setTimeout(() => close(id), 6000);
    },
    [close],
  );
  const host = (
    <ToastHost>
      {items.map((i) => (
        <Toast key={i.id} message={i.message} tone={i.tone} onClose={() => close(i.id)} />
      ))}
    </ToastHost>
  );
  return { toast, host };
}
