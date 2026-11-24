import "./Badge.css";

// A state in a word (web.md § 9.2), coloured by what it means.

export type Meaning = "ok" | "warn" | "bad" | "info" | "plain";

export function Badge({ meaning = "plain", children }: { meaning?: Meaning; children: React.ReactNode }) {
  return <span className={`badge badge--${meaning}`}>{children}</span>;
}
