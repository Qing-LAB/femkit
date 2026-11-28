// The runs going on now (web.md § 2.1, progress): each apply's operation directory as it starts,
// with its plan's steps — what the progress panel shows, from the events and tail routes. The page
// keeps them while it is open; nothing is written.

import { useSyncExternalStore } from "react";
import type { Step } from "../generated/schemas";

export interface Run { address: string; label: string; steps: Step[] }

let runs: Run[] = [];
const listeners = new Set<() => void>();

/** A run started by an apply: its operation directory, what started it, its plan's steps. */
export function started(run: Run): void {
  runs = [run, ...runs.filter((r) => r.address !== run.address)];
  listeners.forEach((l) => l());
}

export function useRuns(): Run[] {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => runs);
}
