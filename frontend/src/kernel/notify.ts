// The one notification stack (web.md § 9.2): what applied, with its Undo; what failed. A view
// says what happened; the stack is drawn once, by the shell.

import { useSyncExternalStore } from "react";
import type { Action } from "../generated/schemas";

export interface Note { id: number; tone: "ok" | "bad" | "info"; text: string; actions: Action[] }

let notes: Note[] = [];
let next = 1;
const listeners = new Set<() => void>();
const changed = () => listeners.forEach((l) => l());

export function notify(tone: Note["tone"], text: string, actions: Action[] = []): void {
  const note = { id: next++, tone, text, actions };
  notes = [...notes.slice(-3), note];
  changed();
  if (tone !== "bad") setTimeout(() => dismiss(note.id), 6000);
}

export function dismiss(id: number): void {
  notes = notes.filter((n) => n.id !== id);
  changed();
}

export function useNotes(): Note[] {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => notes);
}
