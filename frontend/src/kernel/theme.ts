// The theme a person chose (web.md § 10.2): one of theme.toml's themes, or the system's — none chosen —
// offered by the declaration's switch, the system's first; remembered in this browser alone, never on
// the server. The choice is one attribute on the document's root, its name generated with the tokens;
// no element knows a theme.

import { useSyncExternalStore } from "react";
import bundle from "../generated/bundle.json";

const KEPT = "femkit-theme";      // where this browser keeps the choice

let chosen: string | null = (() => {
  try { return localStorage.getItem(KEPT); } catch { return null; }
})();
const listeners = new Set<() => void>();

function show(): void {
  if (chosen) document.documentElement.setAttribute(bundle.attribute, chosen);
  else document.documentElement.removeAttribute(bundle.attribute);
}
show();

/** Choose a theme by its name, or the system's (``null``). */
export function choose(theme: string | null): void {
  chosen = theme;
  try {
    if (chosen) localStorage.setItem(KEPT, chosen); else localStorage.removeItem(KEPT);
  } catch { /* remembered for this page alone */ }
  show();
  listeners.forEach((l) => l());
}

/** The theme chosen, by its name; ``null`` while the system's is followed. */
export function useTheme(): string | null {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => chosen);
}

/** The colour scheme drawn now — the chosen theme's, or the system's — as the tokens set it on the root
 *  (CSS `color-scheme`): what a drawing outside the page's styles, a Mermaid diagram, is told. */
export function scheme(): string {
  return getComputedStyle(document.documentElement).colorScheme;
}
