import type { ReactNode } from "react";
import "./Badge.css";

// A state in a word (web.md § 9.2), a primitive: ``toned``, it takes the colour its nearest ancestor
// binds — a block's word (`--shows`), a severity (`--severity`), a step's word (`--outcome`), each
// bound in the generated tokens — and names no word and no colour of its own.

export function Badge({ toned, children }: { toned?: boolean; children: ReactNode }) {
  return (
    <span className={`badge ${toned ? "badge--toned" : ""}`}>
      {toned && <span className="badge__dot" aria-hidden="true" />}
      {children}
    </span>
  );
}
