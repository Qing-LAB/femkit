// What the server declares about the page (web.md § 8.1), and the operations it serves (§ 1): read
// once by the shell and given to every view and element. The page keeps no list of its own — its
// workspaces, groups, icons, words and controls, and every operation's group, command and values to
// fill, are all read from here.

import { createContext, useContext } from "react";
import type { GraphNode, OperationInfo, Page } from "../generated/schemas";

export interface Declared {
  page: Page;
  operations: Map<string, OperationInfo>;
}

export const Declaration = createContext<Declared | null>(null);

/** The declaration and the operations, as the shell read them. */
export function useDeclared(): Declared {
  const held = useContext(Declaration);
  if (!held) throw new Error("an element is drawn outside the shell, which reads the declaration");
  return held;
}

export type ControlKey = keyof Page["controls"];
export type SayingKey = keyof Page["says"];

/** The words of one of the page's own controls (web.md § 11). */
export function useControl(key: ControlKey) {
  return useDeclared().page.controls[key];
}

/** One of the page's own sentences (web.md § 11). */
export function useSaying(key: SayingKey): string {
  return useDeclared().page.says[key];
}

const PLACEHOLDER = /\{([^{}]+)\}/g;       // a placeholder of the core's grammar, `{name}`

/** One of the page's own sentences that is a template, its placeholders — the core's grammar,
 *  `{name}` (core.md § 2.1) — filled with ``values``. */
export function said(template: string, values: Record<string, string | number>): string {
  return template.replace(PLACEHOLDER, (whole, name: string) => (name in values ? String(values[name]) : whole));
}

/** The first of ``templates`` — a list the declaration gives, its `sentences` — whose every placeholder
 *  ``values`` holds a text for, filled; none when none is. */
export function sentence(templates: string[], values: Record<string, string | undefined>): string | undefined {
  const fills = (template: string) => [...template.matchAll(PLACEHOLDER)].every(([, name]) => !!values[name]);
  const chosen = templates.find(fills);
  return chosen === undefined ? undefined : said(chosen, values as Record<string, string>);
}

/** What a wire of ``type`` carries, as the declaration colours it (`wires`): the declared key the type
 *  is, or the one it is a place of — every place of a group, `group:<place>`, its `group` — never a
 *  key it only begins with (`mesher` is no `mesh`); or none, drawn in the plain wire's. */
export function carried(page: Page, type: string): string | undefined {
  return Object.keys(page.wires).filter((k) => type === k || type.startsWith(`${k}:`))
    .sort((a, b) => b.length - a.length)[0];
}

/** A node's icon: its kind's, under its family (web.md § 8.1). */
export function iconOf(page: Page, node: GraphNode): string | undefined {
  return page.kinds[node.family]?.[node.kind];
}
