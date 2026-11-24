import { icons } from "../generated/icons";
import "./Icon.css";

// An icon the page declaration names (web.md § 9.2); the set is generated from the declaration.

export function Icon({ name, size = 16, label }: { name: string; size?: number; label?: string }) {
  const Shape = (icons as Record<string, typeof icons[keyof typeof icons]>)[name];
  if (!Shape) return <span className="icon icon--missing" aria-hidden="true" />;
  return <Shape className="icon" size={size} strokeWidth={1.8} aria-hidden={label ? undefined : true} aria-label={label} />;
}
