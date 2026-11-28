// Reading a JSON schema fragment, as the server writes it (web.md § 7.3): what kind of input a
// value takes. One home for the operation forms and the model's fields alike.

export type Schema = Record<string, any>;

/** ``schema`` with each `$ref` replaced from ``root``'s definitions, its own description kept. */
export function resolve(schema: Schema, root: Schema = {}): Schema {
  let s = schema;
  while (s && s.$ref) {
    const def = root.$defs?.[String(s.$ref).split("/").pop()!] ?? {};
    s = { ...def, ...Object.fromEntries(Object.entries(s).filter(([k]) => k !== "$ref")) };
  }
  if (s?.allOf?.length === 1) return resolve({ ...s.allOf[0], description: s.description }, root);
  return s ?? {};
}

/** A value that may be left out — `X | None` — and what it is when given. */
export function optional(schema: Schema, root: Schema = {}): { inner: Schema; optional: boolean } {
  const s = resolve(schema, root);
  const alternatives = s.anyOf as Schema[] | undefined;
  if (alternatives?.some((a) => a.type === "null")) {
    const rest = alternatives.filter((a) => a.type !== "null");
    if (rest.length === 1) return { inner: { ...resolve(rest[0], root), description: s.description, default: s.default }, optional: true };
  }
  return { inner: s, optional: false };
}

export type Kind = "fixed" | "choice" | "boolean" | "integer" | "number" | "text" | "list" | "record" | "map" | "json";

/** What input a value takes: held (a const), a choice of a closed list, a number, a text, a list of
 *  these, a record of fields, or JSON as the last resort. */
export function kindOf(schema: Schema, root: Schema = {}): Kind {
  const s = resolve(schema, root);
  if ("const" in s) return "fixed";
  if (s.enum) return "choice";
  if (s.type === "boolean") return "boolean";
  if (s.type === "integer") return "integer";
  if (s.type === "number") return "number";
  if (s.type === "string") return "text";
  if (s.type === "array") return "list";
  if (s.type === "object" && s.properties) return "record";
  if (s.type === "object" && typeof s.additionalProperties === "object") return "map";
  return "json";
}

/** A field's words, from its key: underscores read as spaces. */
export function words(key: string): string {
  return key.replace(/_/g, " ");
}
