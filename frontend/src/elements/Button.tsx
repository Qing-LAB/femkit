import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Icon } from "./Icon";
import "./Button.css";

// A press (web.md § 9.2): primary for what changes things, quiet for what only reads or is the
// page's own, danger for what removes. Its name is its words; a tooltip is never its name.

export type Tone = "primary" | "quiet" | "danger";

export function Button({ tone = "quiet", icon, children, small, bare, ...rest }: {
  tone?: Tone; icon?: string | null; children?: ReactNode; small?: boolean; bare?: boolean;
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  const classes = ["button", `button--${tone}`, small && "button--small", bare && "button--bare",
                   !children && "button--icon"].filter(Boolean).join(" ");
  return (
    <button type="button" className={classes} {...rest}>
      {icon && <Icon name={icon} size={small ? "sm" : "md"} />}
      {children && <span className="button__words">{children}</span>}
    </button>
  );
}
