import type { ReactNode } from "react";
import { Icon } from "./Icon";
import "./Card.css";

// A surface (web.md § 9.2): a heading with its icon, what it holds, and its actions at its foot.

export function Card({ title, icon, aside, children, foot }: {
  title?: ReactNode; icon?: string; aside?: ReactNode; children: ReactNode; foot?: ReactNode;
}) {
  return (
    <section className="card">
      {(title || aside) && (
        <header className="card__head">
          {icon && <span className="card__icon"><Icon name={icon} size="sm" /></span>}
          <h3 className="card__title">{title}</h3>
          {aside && <div className="card__aside">{aside}</div>}
        </header>
      )}
      <div className="card__body">{children}</div>
      {foot && <footer className="card__foot">{foot}</footer>}
    </section>
  );
}
