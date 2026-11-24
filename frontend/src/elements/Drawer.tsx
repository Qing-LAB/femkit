import type { ReactNode } from "react";
import "./Drawer.css";

// A side panel (web.md § 9.2): docked where the screen has room for it, a drawer over the
// canvas where it has not; ``open`` is the narrow screen's.

export function Drawer({ side, open, label, children, onClose }: {
  side: "start" | "end"; open: boolean; label: string; children: ReactNode; onClose: () => void;
}) {
  return (
    <aside className={`drawer drawer--${side} ${open ? "drawer--open" : ""}`} aria-label={label}>
      <button type="button" className="drawer__close" aria-label={`close the ${label}`} onClick={onClose}>×</button>
      {children}
    </aside>
  );
}
