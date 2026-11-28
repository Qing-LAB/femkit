// The text editor's data (web.md § 9.2; ADR 0024): the language a file is read in, by the
// declaration's patterns of names, never by code naming an extension; and what the person typed and
// has not saved, by the file's address, kept while the page is open so a workspace left and come back
// to still holds it — never written anywhere but by the file's save.

import { useSyncExternalStore } from "react";
import type { File, Page } from "../generated/schemas";

export type Language = Page["editor"]["languages"][number]["language"];

/** A name pattern as the declaration writes it: `*` any run of characters, `?` one. */
function pattern(glob: string): RegExp {
  return new RegExp("^" + glob.split("").map((c) => (c === "*" ? ".*" : c === "?" ? "." : c.replace(/[\\^$.|+()[\]{}]/g, "\\$&")))
    .join("") + "$");
}

/** The language ``path``'s file is read in: the first the declaration names it by; none — plain text. */
export function languageOf(editor: Page["editor"], path: string): Language | null {
  const name = path.split("/").pop() ?? path;
  return editor.languages.find((l) => l.files.some((f) => pattern(f).test(name)))?.language ?? null;
}

/** What the person typed into a file and has not saved: the text, and the file as it was when they
 *  began — its save the one that states the SHA-256 it had then (projects.md § 7), so a file changed
 *  since is refused, never written over. */
export interface Edit { text: string; opened: File }

let edits = new Map<string, Edit>();
const listeners = new Set<() => void>();
const changed = () => listeners.forEach((l) => l());

/** Keep ``text`` typed into the file ``opened``, as it was when the person began. */
export function keep(opened: File, text: string): void {
  edits = new Map(edits).set(opened.address, { text, opened });
  changed();
}

/** Leave what was typed into the file ``address``: saved, or left by the person. */
export function forget(address: string): void {
  if (!edits.has(address)) return;
  edits = new Map(edits);
  edits.delete(address);
  changed();
}

export function useEdit(address: string): Edit | undefined {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => edits.get(address));
}
