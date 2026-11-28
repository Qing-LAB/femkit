import { useId } from "react";
import type { Fill } from "../generated/schemas";
import { useControl, useSaying } from "../kernel/declared";
import { kindOf, optional, resolve, Schema, words } from "../kernel/schema";
import { Num, Value, write } from "../kernel/toml";
import { Button } from "./Button";
import { Help } from "./Help";
import "./Field.css";

// One value to fill (web.md §§ 7.2–7.3, 9.2): a `Fill` — its label, its help, its schema fragment, whole
// — the one input every form is drawn with, an operation's request and an action's values alike. A
// number stays the text it was typed as; every value is checked by the server's plan or run, never
// here (§ 5).

function text(v: Value | undefined): string {
  if (v === undefined) return "";
  if (typeof v === "string") return v;
  if (v instanceof Num) return v.text;
  return write(v);
}

/** The input of one schema fragment — a fill's, or a list's item's, a record's key's inside it. */
function Control({ id, name, schema, root, value, onChange, disabled, suggest }: {
  id: string; name: string; schema: Schema; root: Schema; value: Value | undefined;
  onChange: (value: Value | undefined) => void; disabled?: boolean; suggest?: string[];
}) {
  const choose = useControl("select");
  const add = useControl("add");
  const remove = useControl("remove");
  const s = resolve(optional(schema, root).inner, root);
  switch (kindOf(s, root)) {
    case "fixed":
      return <span className="field__fixed">{String(s.const)}</span>;
    case "choice": {
      const options = s.enum as unknown[];
      return (
        <select id={id} className="field__input" value={text(value)} disabled={disabled}
                onChange={(e) => {
                  const picked = options.find((o) => String(o) === e.target.value);
                  onChange(picked === undefined ? undefined : typeof picked === "number" ? new Num(String(picked))
                           : typeof picked === "boolean" ? picked : String(picked));
                }}>
          <option value="">{choose.label}</option>
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
      return <input id={id} className="field__input field__input--mono" inputMode="decimal" value={text(value)}
                    disabled={disabled} spellCheck={false}
                    onChange={(e) => onChange(e.target.value === "" ? undefined : new Num(e.target.value.trim()))} />;
    case "text":
      return (
        <>
          <input id={id} className="field__input" value={text(value)} disabled={disabled} spellCheck={false}
                 pattern={s.pattern} list={suggest ? `${id}-names` : undefined}
                 onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value)} />
          {suggest && <datalist id={`${id}-names`}>{suggest.map((n) => <option key={n} value={n} />)}</datalist>}
        </>
      );
    case "list": {
      const items: (Value | undefined)[] = Array.isArray(value) ? value : [];
      const fixed = s.minItems !== undefined && s.minItems === s.maxItems ? s.minItems as number : null;
      const shown = fixed !== null ? Array.from({ length: fixed }, (_, i) => items[i]) : items;
      const given = (all: (Value | undefined)[]) => {      // an item not given yet is no value
        const held = all.filter((x): x is Value => x !== undefined);
        onChange(held.length ? held : undefined);
      };
      return (
        <span className={`field__list ${fixed !== null ? "field__list--row" : ""}`}>
          {shown.map((v, i) => (
            <span key={i} className="field__item">
              <Control id={`${id}-${i}`} name={`${name} ${i + 1}`} schema={(s.items ?? {}) as Schema} root={root}
                       value={v} disabled={disabled} onChange={(x) => given(shown.map((y, j) => (j === i ? x : y)))} />
              {fixed === null && <Button bare small icon={remove.icon} aria-label={remove.label} title={remove.help}
                                         disabled={disabled} onClick={() => given(shown.filter((_, j) => j !== i))} />}
            </span>
          ))}
          {fixed === null && <Button small icon={add.icon} title={add.help} disabled={disabled}
                                     onClick={() => onChange([...items, undefined] as Value[])}>{add.label}</Button>}
        </span>
      );
    }
    case "record": {
      const record = value && typeof value === "object" && !Array.isArray(value) && !(value instanceof Num)
        ? value as Record<string, Value> : {};
      const fixedKeys = Object.fromEntries(Object.entries((s.properties ?? {}) as Record<string, Schema>)
        .map(([k, sub]) => [k, resolve(sub, root)]).filter(([, sub]) => "const" in (sub as Schema))
        .map(([k, sub]) => [k, String((sub as Schema).const)]));
      const set = (next: Record<string, Value>) => onChange({ ...next, ...fixedKeys });   // a fixed key always written
      return (
        <span className="field__record">
          {Object.entries((s.properties ?? {}) as Record<string, Schema>).map(([key, sub]) => (
            <span key={key} className="field__key">
              <label className="field__label" htmlFor={`${id}-${key}`}><span className="field__name">{words(key)}</span></label>
              <Control id={`${id}-${key}`} name={key} schema={sub} root={root} value={record[key]} disabled={disabled}
                       onChange={(v) => {
                         const next = { ...record };
                         if (v === undefined) delete next[key]; else next[key] = v;
                         set(next);
                       }} />
            </span>
          ))}
        </span>
      );
    }
    default:
      return <textarea id={id} className="field__input field__input--mono" defaultValue={value === undefined ? "" : JSON.stringify(value)}
                       disabled={disabled} spellCheck={false} onChange={(e) => {
                         try { onChange(e.target.value.trim() ? JSON.parse(e.target.value) : undefined); }
                         catch { onChange(e.target.value); }
                       }} />;
  }
}

export function Field({ fill, value, onChange, disabled, suggest }: {
  fill: Fill; value: Value | undefined; onChange: (value: Value | undefined) => void; disabled?: boolean; suggest?: string[];
}) {
  const id = useId();
  const optionalWord = useSaying("optional");
  const schema = fill.json_schema as Schema;
  return (
    <div className={`field field--${kindOf(resolve(optional(schema, schema).inner, schema), schema)}`}>
      <label className="field__label" htmlFor={id}>
        <span className="field__name">{fill.label}</span>
        {!fill.required && <span className="field__optional">{optionalWord}</span>}
        <Help help={fill.help} />
      </label>
      <Control id={id} name={fill.field} schema={schema} root={schema} value={value} onChange={onChange}
               disabled={disabled} suggest={suggest} />
      {fill.example && <span className="field__hint">{fill.example}</span>}
    </div>
  );
}
