import { useEffect, useRef, type ReactNode } from "react";
import "./Dialog.css";

// The one dialog (web.md § 9.2), never the browser's own: Esc and a click off it close it.

export function Dialog({ title, children, foot, onClose, wide }: {
  title: ReactNode; children: ReactNode; foot?: ReactNode; onClose: () => void; wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current!;
    if (!d.open) d.showModal();
    const cancel = (e: Event) => { e.preventDefault(); onClose(); };
    d.addEventListener("cancel", cancel);
    return () => d.removeEventListener("cancel", cancel);
  }, [onClose]);
  return (
    <dialog ref={ref} className={`dialog ${wide ? "dialog--wide" : ""}`} onClick={(e) => { if (e.target === ref.current) onClose(); }}>
      <div className="dialog__surface">
        <header className="dialog__head"><h2 className="dialog__title">{title}</h2>
          <button type="button" className="dialog__close" aria-label="close" onClick={onClose}>×</button></header>
        <div className="dialog__body">{children}</div>
        {foot && <footer className="dialog__foot">{foot}</footer>}
      </div>
    </dialog>
  );
}
