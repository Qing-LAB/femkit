// The one notification stack (web.md § 9.2): what applied; what failed. A view says what
// happened; the stack is drawn once, by the shell. How many notices stay at once is the
// declaration's (`notices`); how long a notice stays, the theme's.

import { useSyncExternalStore } from "react";
import { measure } from "./tokens";

export interface Note { id: number; tone: "ok" | "bad"; text: string; title?: string }

let kept = 1;
let notes: Note[] = [];
let next = 1;
const listeners = new Set<() => void>();
const changed = () => listeners.forEach((l) => l());

/** How many notices the stack shows at once, as the declaration says: set by the shell. */
export function keep(count: number): void {
  kept = count;
}

/** Say ``text`` — what it is about, under its ``title`` — in the stack, in the tone of how it went. */
export function notify(tone: Note["tone"], text: string, title?: string): void {
  const note = { id: next++, tone, text, title };
  notes = [...notes, note].slice(-kept);
  changed();
  if (tone !== "bad") setTimeout(() => dismiss(note.id), measure("motion-linger"));
}

export function dismiss(id: number): void {
  notes = notes.filter((n) => n.id !== id);
  changed();
}

export function useNotes(): Note[] {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => notes);
}
