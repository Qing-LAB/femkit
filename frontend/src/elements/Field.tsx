import { useId } from "react";
import type { Help as HelpPart } from "../generated/schemas";
import { kindOf, optional, resolve, Schema, words } from "../kernel/schema";
import { isNumber, Num, read, Value, write } from "../kernel/toml";
import { Help } from "./Help";
import "./Field.css";

// One value from its schema fragment (web.md § 9.2): the one input every form is drawn with —
// an operation's request and a model's value alike. A number stays the text it was typed as.

export interface FieldProps {
  name: string;
  label?: string;
  schema: Schema;
  root?: Schema;                 // where the fragment's `$ref`s resolve
  value: Value | undefined;
  onChange: (value: Value | undefined) => void;
  help?: HelpPart | null;
  error?: string | null;
  names?: string[];              // for a reference: the names it may take
  disabled?: boolean;
}

const QUANTITY = /^\s*([+-]?[\d.]+(?:[eE][+-]?\d+)?)\s*(\S*)\s*$/;

function text(v: Value | undefined): string {
  if (v === undefined) return "";
  if (typeof v === "string") return v;
  if (v instanceof Num) return v.text;
  return write(v);
}

export function Field({ name, label, schema, root = {}, value, onChange, help, error, names, disabled }: FieldProps) {
  const id = useId();
  const { inner, optional: canOmit } = optional(schema, root);
  const s = resolve(inner, root);
  const kind = kindOf(s, root);
  const hint = s.description as string | undefined;
  const choices = names ?? null;
  const control = (() => {
    if (choices && (kind === "text" || kind === "quantity")) {
      return (
        <select id={id} className="field__input" value={text(value)} disabled={disabled}
                onChange={(e) => onChange(e.target.value || undefined)}>
          <option value="">{canOmit ? "—" : "choose…"}</option>
          {choices.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      );
    }
    switch (kind) {
      case "fixed":
        return <span className="field__fixed">{String(s.const)}</span>;
      case "choice": {
        const options = s.enum as unknown[];
        const shown = text(value);
        return (
          <select id={id} className="field__input" value={shown} disabled={disabled}
                  onChange={(e) => {
                    const picked = options.find((o) => String(o) === e.target.value);
                    onChange(picked === undefined ? undefined : typeof picked === "number" ? new Num(String(picked)) :
                             typeof picked === "boolean" ? picked : String(picked));
                  }}>
            <option value="">{canOmit ? "—" : "choose…"}</option>
            {options.map((o) => <option key={String(o)} value={String(o)}>{String(o)}</option>)}
          </select>
        );
      }
      case "boolean":
        return (
          <label className="field__switch">
            <input id={id} type="checkbox" checked={value === true} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
            <span className="field__track" aria-hidden="true" />
          </label>
        );
      case "integer":
      case "number":
        return <input id={id} className="field__input field__input--mono" inputMode="decimal" value={text(value)} disabled={disabled}
                      spellCheck={false} onChange={(e) => onChange(e.target.value === "" ? undefined : new Num(e.target.value.trim()))} />;
      case "quantity": {
        const units = (s.units as string[] | undefined) ?? [];
        const bare = Array.isArray(s.anyOf);    // a coordinate: a bare number in the frame's unit, or a length
        const shown = text(value);
        const m = QUANTITY.exec(shown);
        const set = (t: string) => onChange(t === "" ? undefined : bare && isNumber(t) ? new Num(t.trim()) : t);
        return (
          <span className="field__quantity">
            <input id={id} className="field__input field__input--mono" value={shown} disabled={disabled} spellCheck={false}
                   placeholder={units.length ? `a value in ${units.includes("m") ? "m" : units[0]}` : "a value or an expression"}
                   onChange={(e) => set(e.target.value)} />
            {units.length > 0 && (
              <select className="field__unit" aria-label={`${label ?? words(name)}: unit`} disabled={disabled}
                      value={m?.[2] ?? ""} onChange={(e) => set(`${m?.[1] ?? "1"} ${e.target.value}`.trim())}>
                <option value="">unit</option>
                {units.map((u) => <option key={u}>{u}</option>)}
              </select>
            )}
          </span>
        );
      }
      case "text":
        return <input id={id} className="field__input" value={text(value)} disabled={disabled} spellCheck={false}
                      pattern={s.pattern} onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value)} />;
      case "list": {
        const items = Array.isArray(value) ? value : [];
        const fixed = s.minItems !== undefined && s.minItems === s.maxItems ? s.minItems as number : null;
        const shown = fixed !== null ? Array.from({ length: fixed }, (_, i) => items[i]) : items;
        const item = (s.items ?? {}) as Schema;
        const put = (i: number, v: Value | undefined) => {
          const next = [...shown];
          next[i] = v as Value;
          onChange(next.every((x) => x === undefined) ? undefined : next.map((x) => x ?? ""));
        };
        return (
          <span className={`field__list ${fixed !== null ? "field__list--row" : ""}`}>
            {shown.map((v, i) => (
              <span key={i} className="field__item">
                <Field name={`${name}.${i}`} label={`${label ?? words(name)} ${i + 1}`} schema={item} root={root} value={v}
                       onChange={(x) => put(i, x)} disabled={disabled} names={names} />
                {fixed === null && <button type="button" className="field__remove" aria-label="remove" disabled={disabled}
                                           onClick={() => onChange(items.filter((_, j) => j !== i))}>×</button>}
              </span>
            ))}
            {fixed === null && <button type="button" className="field__add" disabled={disabled}
                                       onClick={() => onChange([...items, ""])}>+ add</button>}
          </span>
        );
      }
      case "record": {
        const record = value && typeof value === "object" && !Array.isArray(value) && !(value instanceof Num)
          ? value as Record<string, Value> : {};
        const required = new Set<string>((s.required as string[]) ?? []);
        return (
          <span className="field__record">
            {Object.entries((s.properties ?? {}) as Record<string, Schema>).map(([key, sub]) => (
              <Field key={key} name={key} schema={required.has(key) ? sub : { anyOf: [sub, { type: "null" }] }} root={root}
                     value={"const" in resolve(sub, root) ? resolve(sub, root).const : record[key]} disabled={disabled}
                     onChange={(v) => {
                       const next = { ...record };
                       if (v === undefined) delete next[key]; else next[key] = v;
                       onChange(next);
                     }} />
            ))}
          </span>
        );
      }
      default:
        return <textarea id={id} className="field__input field__input--mono" rows={3} value={text(value)} disabled={disabled}
                         spellCheck={false} onChange={(e) => {
                           try { onChange(e.target.value.trim() ? read(e.target.value) : undefined); } catch { onChange(e.target.value); }
                         }} />;
    }
  })();
  return (
    <div className={`field field--${kind} ${error ? "field--wrong" : ""}`}>
      {kind !== "list" || label ? (
        <label className="field__label" htmlFor={id}>
          {label ?? words(name)}{canOmit && <span className="field__optional">optional</span>}<Help help={help} />
        </label>
      ) : null}
      {control}
      {hint && !help && kind !== "record" && <span className="field__hint">{hint}</span>}
      {error && <span className="field__error" role="alert">{error}</span>}
    </div>
  );
}
