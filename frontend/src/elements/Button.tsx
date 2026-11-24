import type { ReactNode } from "react";
import { Icon } from "./Icon";
import "./Button.css";

// A press (web.md § 9.2): primary for the one thing a place is for, quiet for the rest, danger
// for what removes. Its name is its words; a tooltip is never its name.

export type Tone = "primary" | "quiet" | "danger" | "ghost";

export function Button({ tone = "quiet", icon, children, busy, small, ...rest }: {
  tone?: Tone; icon?: string; children?: ReactNode; busy?: boolean; small?: boolean;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button type="button" className={`button button--${tone} ${small ? "button--small" : ""} ${busy ? "button--busy" : ""}`}
            aria-busy={busy || undefined} {...rest}>
      {icon && <Icon name={icon} size={small ? 14 : 16} />}
      {children && <span>{children}</span>}
    </button>
  );
}
