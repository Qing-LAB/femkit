// The actions open in dialogs (web.md § 9.1): each held here, apart from the press that opened it, so
// its outcome — its report and next steps — stays until the person closes it, though the change it made
// redraws, or removes, the press. Drawn once, by the shell — in a dialog, or docked beside the
// workspaces, so a plan's marks are seen on every diagram while it is shown (a save's impact, § 2.4).

import { useSyncExternalStore } from "react";
import type { Act, Given } from "./action";

/** An action open: the values its holder gave it, whether it is docked, and what its holder is told
 *  of how it ended. */
export interface Opened {
  id: number;
  act: Act;
  values?: Given;
  docked?: boolean;
  done?: (ok: boolean) => void;
}

let opened: Opened[] = [];
let next = 1;
const listeners = new Set<() => void>();
const changed = () => listeners.forEach((l) => l());

/** Open ``act`` in a dialog of its own, or docked. */
export function open(act: Act, how: Omit<Opened, "id" | "act"> = {}): void {
  opened = [...opened, { id: next++, act, ...how }];
  changed();
}

/** The dialog ``id`` closed by the person. */
export function close(id: number): void {
  opened = opened.filter((o) => o.id !== id);
  changed();
}

export function useOpened(): Opened[] {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => opened);
}
