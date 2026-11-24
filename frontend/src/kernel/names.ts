// The names a reference may take (web.md § 7.2): a view that shows a document says, for the
// node kinds a fill or a field accepts — `material`, `region:boundary` — which names exist.
// Where no view says, none are known, and the person types the name.

import { createContext } from "react";

export type Names = (accepts: string[]) => string[] | undefined;

export const NamesOf = createContext<Names>(() => undefined);
