import type { ReactNode } from "react";
import { Icon } from "./Icon";
import "./Empty.css";

// What to do first, where there is nothing to show yet (web.md § 9.2): its words are the
// declaration's or the server's.

export function Empty({ icon, title, children }: { icon: string; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty__mark"><Icon name={icon} size={28} /></div>
      <p className="empty__title">{title}</p>
      {children && <div className="empty__more">{children}</div>}
    </div>
  );
}
