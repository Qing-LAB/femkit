// The document viewer's address (web.md § 2.3): one grammar — a document by its path, at a section —
// written and read here alone, for the client, the viewer and every link a rendered document holds.

import bundle from "../generated/bundle.json";

export interface Place { doc?: string; at?: string }

/** The fragment naming a document and its section: what a link inside the viewer is. */
export function fragment(place: Place, more: Record<string, string> = {}): string {
  const params = new URLSearchParams(more);
  if (place.doc) params.set("doc", place.doc);
  if (place.at) params.set("at", place.at);
  return "#" + params.toString();
}

/** The viewer's address for a document and its section, opened from the page: its token handed over
 *  in the fragment, as the page's own was (web.md § 5). */
export function viewer(token: string, place: Place = {}): string {
  return bundle.addresses.documents + fragment(place, { token });
}

/** The document and section the address names now. */
export function place(): Place {
  const params = new URLSearchParams(window.location.hash.slice(1));
  return { doc: params.get("doc") ?? undefined, at: params.get("at") ?? undefined };
}
