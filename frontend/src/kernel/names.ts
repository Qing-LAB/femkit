// The names a reference may take (web.md § 7.2): a view that shows a document says, for the
// node kinds a fill or a field accepts — `material`, `region:boundary` — which names exist.

import { createContext } from "react";

export type Names = (accepts: string[]) => string[];

export const NamesOf = createContext<Names>(() => []);
