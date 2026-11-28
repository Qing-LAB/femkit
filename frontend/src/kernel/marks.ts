// What a plan shown marks on the diagrams (web.md § 2.4: a save's impact "marked on both
// diagrams"): the addresses its findings are about, and the findings themselves, for as long as the
// plan is shown — whichever workspace is in view.

import { useSyncExternalStore } from "react";
import type { Issue } from "../generated/schemas";

export interface Marks { by: number; addresses: ReadonlySet<string>; issues: Issue[] }

const NONE: Marks = { by: 0, addresses: new Set(), issues: [] };
let marks = NONE;
let next = 1;
const listeners = new Set<() => void>();
const changed = () => listeners.forEach((l) => l());

/** Mark what ``issues`` are about; what it gives back clears them again, and nothing a later mark set. */
export function mark(issues: Issue[]): () => void {
  const by = next++;
  marks = { by, addresses: new Set(issues.map((i) => i.subject)), issues };
  changed();
  return () => {
    if (marks.by !== by) return;
    marks = NONE;
    changed();
  };
}

export function useMarks(): Marks {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => marks);
}
