import type { JsonSchema } from "./api";
import { kindOf, label, unwrapOptional } from "./schema";

// The request form, from its schema alone. A field left empty is not sent, so the server's
// default holds; every value is checked by the plan or run route, never here (api.md § 5.5).

export type Values = Record<string, string | boolean>;

export function requestFrom(schema: JsonSchema, values: Values): { request: Record<string, unknown>; problems: string[] } {
  const request: Record<string, unknown> = {};
  const problems: string[] = [];
  for (const [name, raw] of Object.entries(schema.properties ?? {})) {
    const { inner } = unwrapOptional(raw, schema);
    const value = values[name];
    if (value === undefined || value === "") continue;
    const kind = kindOf(inner);
    if (kind === "boolean") {
      if (value !== (inner.default ?? false)) request[name] = value;
    } else if (kind === "integer" || kind === "number") {
      const n = Number(value);
      if (Number.isNaN(n)) problems.push(`${label(name)}: not a number`);
      else request[name] = n;
    } else if (kind === "list") {
      const items = String(value).split("\n").map((l) => l.trim()).filter(Boolean);
      request[name] = inner.items?.type === "string" ? items : items.map(Number);
    } else if (kind === "json") {
      try {
        request[name] = JSON.parse(String(value));
      } catch {
        problems.push(`${label(name)}: not JSON`);
      }
    } else {
      request[name] = value;
    }
  }
  return { request, problems };
}

export function Form({ schema, values, onChange, disabled }: {
  schema: JsonSchema;
  values: Values;
  onChange: (v: Values) => void;
  disabled: boolean;
}) {
  const fields = Object.entries(schema.properties ?? {});
  if (fields.length === 0) return <p className="muted">It takes no inputs.</p>;
  const required = new Set(schema.required ?? []);
  return (
    <div className="form">
      {fields.map(([name, raw]) => {
        const { inner, optional } = unwrapOptional(raw, schema);
        const kind = kindOf(inner);
        const value = values[name];
        const id = `field-${name}`;
        const set = (v: string | boolean) => onChange({ ...values, [name]: v });
        const hint = inner.default !== undefined && inner.default !== null && kind !== "boolean"
          ? `default ${JSON.stringify(inner.default)}` : optional ? "optional" : required.has(name) ? "required" : "";
        return (
          <div className={`field field-${kind}`} key={name}>
            {kind === "boolean" ? (
              <label className="check" htmlFor={id}>
                <input id={id} type="checkbox" disabled={disabled}
                  checked={value === undefined ? Boolean(inner.default) : Boolean(value)}
                  onChange={(e) => set(e.target.checked)} />
                <span className="name">{label(name)}</span>
              </label>
            ) : (
              <label className="name" htmlFor={id}>{label(name)}{hint && <span className="hint">{hint}</span>}</label>
            )}
            {kind === "enum" && (
              <select id={id} disabled={disabled} value={String(value ?? "")} onChange={(e) => set(e.target.value)}>
                <option value="">{inner.default != null ? `(default: ${String(inner.default)})` : "—"}</option>
                {inner.enum!.map((o) => <option key={String(o)} value={String(o)}>{String(o)}</option>)}
              </select>
            )}
            {(kind === "string" || kind === "integer" || kind === "number") && (
              <input id={id} type="text" inputMode={kind === "string" ? "text" : "decimal"} disabled={disabled}
                value={String(value ?? "")} placeholder={inner.default != null ? String(inner.default) : ""}
                onChange={(e) => set(e.target.value)} spellCheck={false} />
            )}
            {(kind === "list" || kind === "json") && (
              <textarea id={id} rows={3} disabled={disabled} value={String(value ?? "")} spellCheck={false}
                placeholder={kind === "list" ? "one per line" : "JSON"} onChange={(e) => set(e.target.value)} />
            )}
            {inner.description && <p className="description">{inner.description}</p>}
          </div>
        );
      })}
    </div>
  );
}
