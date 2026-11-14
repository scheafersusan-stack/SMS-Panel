import { useEffect, useId, useRef, type ReactNode } from "react";
import { Icon } from "./Icon";

const FOCUSABLE = 'a[href],button:not([disabled]),input,select,textarea,[tabindex]:not([tabindex="-1"])';

/** Blocking dialog: closes on Esc and on the scrim, keeps Tab focus inside, restores focus on close. */
export function Modal({ title, onClose, footer, children }: { title: string; onClose: () => void; footer?: ReactNode; children?: ReactNode }) {
  const titleId = useId();
  const ref = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const root = ref.current;
    root?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onCloseRef.current();
        return;
      }
      if (e.key !== "Tab" || !root) return;
      const items = Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE));
      const first = items[0];
      const last = items[items.length - 1];
      if (!first || !last) return;
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, []);

  return (
    <div
      className="modal-host"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="ns-modal" role="dialog" aria-modal="true" aria-labelledby={titleId} ref={ref}>
        <div className="ns-modal-head">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="ns-close" aria-label="بستن" onClick={onClose}>
            <Icon name="x" />
          </button>
        </div>
        <div className="ns-modal-body">{children}</div>
        {footer ? <div className="ns-modal-foot">{footer}</div> : null}
      </div>
    </div>
  );
}
