import type { ReactNode } from "react";
import { useControl } from "../kernel/declared";
import { Button } from "./Button";
import "./Drawer.css";

// A side panel over the canvas on a narrow screen (web.md § 9.2); ``open`` is the page state's.

export function Drawer({ side, open, label, children, onClose }: {
  side: "start" | "end" | "bottom"; open: boolean; label: string; children: ReactNode; onClose: () => void;
}) {
  const close = useControl("close");
  return (
    <>
      <div className={`drawer__scrim ${open ? "drawer__scrim--open" : ""}`} onClick={onClose} aria-hidden="true" />
      <aside className={`drawer drawer--${side} ${open ? "drawer--open" : ""}`} aria-label={label} aria-hidden={!open}>
        <header className="drawer__head">
          <span className="drawer__title">{label}</span>
          <Button bare small icon={close.icon} aria-label={close.label} title={close.help} onClick={onClose} />
        </header>
        <div className="drawer__body">{children}</div>
      </aside>
    </>
  );
}
