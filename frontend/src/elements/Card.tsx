import type { ReactNode } from "react";
import "./Card.css";

// A surface (web.md § 9.2): a heading, what it holds, and its actions at its foot.

export function Card({ title, aside, children, foot }: { title?: ReactNode; aside?: ReactNode; children: ReactNode; foot?: ReactNode }) {
  return (
    <section className="card">
      {(title || aside) && <header className="card__head"><h3 className="card__title">{title}</h3>{aside}</header>}
      <div className="card__body">{children}</div>
      {foot && <footer className="card__foot">{foot}</footer>}
    </section>
  );
}
