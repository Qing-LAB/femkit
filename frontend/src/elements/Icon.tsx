import { icons } from "../generated/icons";
import "./Icon.css";

// An icon the page declaration names (web.md § 9.2); the set is generated from the declaration.
// Its size is a token, by name: `xs`, `sm`, `md` (the default), `lg`, `xl`.

export type IconSize = "xs" | "sm" | "md" | "lg" | "xl";

export function Icon({ name, size = "md", label }: { name?: string | null; size?: IconSize; label?: string }) {
  const Shape = name ? (icons as Record<string, (typeof icons)[keyof typeof icons]>)[name] : undefined;
  if (!Shape) return <span className={`icon icon--${size} icon--missing`} aria-hidden="true" />;
  return <Shape className={`icon icon--${size}`} aria-hidden={label ? undefined : true} aria-label={label} />;
}
