// A context's choices (web.md § 8.1): the read-only operation the declaration names, run for the
// context chosen so far, its rows read by the keys the declaration gives — the value each row holds
// and what a person reads.

import type { ContextPart } from "../generated/schemas";
import { useDeclared } from "./declared";
import { useDocument } from "./document";
import type { PageState } from "./state";

export interface Choice { value: string; label: string; row: Record<string, unknown> }

export function useChoices(part: ContextPart, state: PageState): Choice[] | null {
  const { operations } = useDeclared();
  const read = useDocument(operations.get(part.choices), state, part.depends);
  if (read.kind !== "ok") return null;
  const rows = (read.value.result as Record<string, unknown>)[part.rows];
  return (Array.isArray(rows) ? rows : []).map((held) => {
    const row = (typeof held === "object" && held !== null ? held : {}) as Record<string, unknown>;
    const value = String(part.value_key ? row[part.value_key] : held);
    return { value, label: part.label_key ? String(row[part.label_key]) : value, row };
  });
}

/** The contexts a workspace shows a chooser for (web.md § 8.1): those it needs, and those its
 *  document's request takes — by each field's `context` annotation — in the declaration's order. */
export function contextsOf(needs: string[], request: { properties?: Record<string, { context?: string }> } | undefined,
                           context: ContextPart[]): ContextPart[] {
  const taken = new Set<string>([...needs, ...Object.values(request?.properties ?? {}).flatMap((p) => (p.context ? [p.context] : []))]);
  return context.filter((c) => taken.has(c.key));
}
