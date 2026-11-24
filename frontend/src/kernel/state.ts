// The page state (web.md § 9.1): one store — the context, the workspace, the selection, the open
// drawer — mirrored in the address's fragment both ways. A change of context or workspace is a
// history entry; a selection replaces the current one. Nothing is applied from an address.

import { useSyncExternalStore } from "react";

export interface PageState {
  workspace?: string;
  project?: string;
  study?: string;
  environment?: string;
  selected?: string;
  operation?: string;
}

const KEYS: (keyof PageState)[] = ["workspace", "project", "study", "environment", "selected", "operation"];
const KEPT = "femkit-project";   // a convenience only: the last project, for a page opened bare

function fromAddress(): PageState {
  const params = new URLSearchParams(window.location.hash.slice(1));
  const state: PageState = {};
  for (const k of KEYS) {
    const v = params.get(k);
    if (v) state[k] = v;
  }
  if (!state.project) {
    try { state.project = localStorage.getItem(KEPT) ?? undefined; } catch { /* storage refused */ }
  }
  return state;
}

function toAddress(state: PageState): string {
  const params = new URLSearchParams();
  for (const k of KEYS) if (state[k]) params.set(k, state[k]!);
  return "#" + params.toString();
}

let current: PageState = fromAddress();
const listeners = new Set<() => void>();

function changed() {
  current = fromAddress();
  listeners.forEach((l) => l());
}

window.addEventListener("hashchange", changed);
window.addEventListener("popstate", changed);

/** A move of the page: a history entry, or — for a selection alone — the current one replaced. */
export function go(patch: PageState): void {
  const next = { ...current, ...patch };
  for (const k of KEYS) if (next[k] === undefined || next[k] === "") delete next[k];
  if (patch.project !== undefined && patch.project !== current.project) {
    delete next.study; delete next.selected;
    try { localStorage.setItem(KEPT, patch.project); } catch { /* a convenience only */ }
  }
  if (patch.study !== undefined && patch.study !== current.study) delete next.selected;
  const selectionOnly = Object.keys(patch).every((k) => k === "selected");
  const address = window.location.pathname + window.location.search + toAddress(next);
  if (selectionOnly) history.replaceState(null, "", address);
  else history.pushState(null, "", address);
  changed();
}

export function usePage(): PageState {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => current);
}
