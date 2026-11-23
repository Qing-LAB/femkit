// Reading a request model's JSON schema, as pydantic writes it: the page knows no operation,
// only the schema (api.md § 5.2).
import type { JsonSchema } from "./api";

export function resolve(schema: JsonSchema, root: JsonSchema): JsonSchema {
  let s = schema;
  while (s.$ref) {
    const name = s.$ref.split("/").pop()!;
    s = { ...root.$defs?.[name], description: s.description ?? root.$defs?.[name]?.description };
  }
  if (s.allOf && s.allOf.length === 1) return resolve({ ...s.allOf[0], description: s.description }, root);
  return s;
}

/** A field that may be left empty: `X | None`, written by pydantic as anyOf with null. */
export function unwrapOptional(schema: JsonSchema, root: JsonSchema): { inner: JsonSchema; optional: boolean } {
  const s = resolve(schema, root);
  if (s.anyOf) {
    const rest = s.anyOf.filter((a) => a.type !== "null");
    if (rest.length === 1) {
      return { inner: { ...resolve(rest[0], root), description: s.description, default: s.default }, optional: true };
    }
  }
  return { inner: s, optional: false };
}

export type Kind = "boolean" | "integer" | "number" | "string" | "enum" | "list" | "json";

export function kindOf(s: JsonSchema): Kind {
  if (s.enum) return "enum";
  if (s.type === "boolean") return "boolean";
  if (s.type === "integer") return "integer";
  if (s.type === "number") return "number";
  if (s.type === "string") return "string";
  if (s.type === "array" && s.items && ["string", "integer", "number"].includes(String(s.items.type))) return "list";
  return "json";
}

export function label(name: string): string {
  return name.replace(/_/g, " ");
}
