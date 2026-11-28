// A read-only operation's document, for a workspace or a panel (web.md § 8.1): its request made from
// the page's context — each request field the server marks with the context it takes (`context`,
// core.md § 2) — run through the client, and read again when the context changes or a change was
// applied. The page names no field: the request model says which context each field takes.

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import type { OperationInfo, RunAnswer } from "../generated/schemas";
import { Outcome, server } from "./client";
import type { PageState } from "./state";

/** The request ``op`` takes from the context ``state``: each field marked with a context, the value
 *  chosen for it. */
export function requestFor(op: OperationInfo, state: PageState): { request: Record<string, string> } {
  const schema = op.request as { properties?: Record<string, { context?: string }> };
  const request: Record<string, string> = {};
  for (const [field, part] of Object.entries(schema.properties ?? {})) {
    if (part.context && state[part.context]) request[field] = state[part.context];
  }
  return { request };
}

// Each apply that ended moves the generation on: every document is read again, since what it shows
// may have changed (web.md § 8.5).
let generation = 0;
const listeners = new Set<() => void>();

/** Say that a change was applied: every document on the page is read again. */
export function changed(): void {
  generation += 1;
  listeners.forEach((l) => l());
}

function useGeneration(): number {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => generation);
}

export type Read = { kind: "waiting" } | { kind: "incomplete" } | Outcome<RunAnswer>;

/** The document of the read-only operation ``op`` for the context ``state``: waiting while it is
 *  read, incomplete while a context it ``needs`` — as the declaration says what a workspace or a
 *  panel needs — is not chosen, else the client's outcome. */
export function useDocument(op: OperationInfo | undefined, state: PageState, needs: string[] = []): Read {
  const request = op ? requestFor(op, state).request : {};
  const complete = !!op && needs.every((n) => state[n]);
  const key = op ? `${op.name} ${JSON.stringify(request)}` : "";
  const fresh = useGeneration();
  const [read, setRead] = useState<{ key: string; outcome: Read }>({ key: "", outcome: { kind: "waiting" } });
  const load = useCallback(async (live: () => boolean) => {
    if (!op) return;
    const outcome = await server.run(op.words, request);
    if (live()) setRead({ key, outcome });
  }, [key]);   // the request is the key's
  useEffect(() => {
    if (!op || !complete) return;
    let alive = true;
    void load(() => alive);
    return () => { alive = false; };
  }, [key, complete, fresh, load]);
  if (!op || !complete) return { kind: "incomplete" };
  return read.key === key ? read.outcome : { kind: "waiting" };
}
