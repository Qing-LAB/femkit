// The page state (web.md § 9.1): one store — the context, the workspace, the selection, the open
// drawer — the first three mirrored in the address's fragment both ways. A change of context or
// workspace is a history entry; a selection replaces the current one. Nothing is applied from an
// address, and an action is never in one. Which keys are the context, and what depends on what, are
// the declaration's (§ 8.1): a context changed clears every context that depends on it, and the
// selection.

import { useSyncExternalStore } from "react";
import type { ContextPart } from "../generated/schemas";

/** The page's own keys beside the context's: the workspace in view, the node selected, the
 *  operation the Operations workspace shows. */
export const WORKSPACE = "workspace";
export const SELECTED = "selected";
export const OPERATION = "operation";

export type PageState = Record<string, string>;
const HIDDEN = new Set(["token"]);   // the access token, taken by the client and never mirrored

function fromAddress(): PageState {
  const state: PageState = {};
  new URLSearchParams(window.location.hash.slice(1)).forEach((v, k) => { if (v && !HIDDEN.has(k)) state[k] = v; });
  return state;
}

let current: PageState = fromAddress();
let drawer: string | null = null;
const listeners = new Set<() => void>();
const changed = () => listeners.forEach((l) => l());

window.addEventListener("hashchange", () => { current = fromAddress(); changed(); });

/** Every context that depends on ``key``, through the declaration's `depends`, transitively. */
function dependents(key: string, context: ContextPart[]): string[] {
  const direct = context.filter((c) => (c.depends as string[]).includes(key)).map((c) => c.key as string);
  return [...direct, ...direct.flatMap((d) => dependents(d, context))];
}

/** A move of the page: a history entry, or — for a selection alone, or a choice the page made itself
 *  (``replace``) — the current one replaced. */
export function go(patch: PageState, context: ContextPart[] = [], replace = false): void {
  const next: PageState = { ...current, ...patch };
  for (const key of Object.keys(patch)) {
    if (patch[key] === current[key] || !context.some((c) => c.key === key)) continue;
    for (const d of dependents(key, context)) delete next[d];
    if (!(SELECTED in patch)) delete next[SELECTED];
  }
  for (const k of Object.keys(next)) if (!next[k]) delete next[k];
  const address = window.location.pathname + window.location.search + "#" + new URLSearchParams(next).toString();
  if (replace || Object.keys(patch).every((k) => k === SELECTED)) history.replaceState(null, "", address);
  else history.pushState(null, "", address);
  current = next;
  changed();
}

/** The page state now. */
export function usePage(): PageState {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => current);
}

/** Open a drawer by its name, or close it (``null``): held by the page, never in the address. */
export function openDrawer(name: string | null): void {
  drawer = name;
  changed();
}

export function useDrawer(): string | null {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => drawer);
}
