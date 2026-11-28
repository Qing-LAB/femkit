import type { Field } from "../generated/schemas";
import { said, useDeclared } from "../kernel/declared";
import { optional, type Schema } from "../kernel/schema";
import { Num, write, type Value } from "../kernel/toml";
import "./Key.css";

// One key a file may hold (web.md §§ 7.3, 8.3, 9.2): a `Field` of its node's keys — its path, its
// sentence, whether it must be stated, its choices and units as its schema fragment states them, and
// where it is defined — as the text editor shows it on hover and beside a suggestion. Its words are the
// server's.

/** A value of a fragment's closed list, as the file writes it. */
export function written(v: unknown): string {
  return write(typeof v === "number" ? new Num(String(v)) : (v as Value));
}

export function Key({ field }: { field: Field }) {
  const says = useDeclared().page.says;
  const schema = field.json_schema as Schema;
  const s = optional(schema, schema).inner;
  const choices = (s.enum ?? []) as unknown[];
  const units = (s.units ?? []) as unknown[];
  const doc = field.help?.doc;
  return (
    <div className="key">
      <p className="key__head">
        <code className="key__name">{field.key ?? field.label}</code>
        {!field.required && <span className="key__optional">{says.optional}</span>}
      </p>
      {field.help && <p className="key__sentence">{field.help.sentence}</p>}
      {choices.length > 0 && <p className="key__values">{choices.map((c) => <code key={String(c)}>{written(c)}</code>)}</p>}
      {units.length > 0 && <p className="key__values">{units.map((u) => <code key={String(u)}>{String(u)}</code>)}</p>}
      {doc && <p className="key__where">{doc.section ? said(says.section, { document: doc.document, section: doc.section }) : doc.document}</p>}
    </div>
  );
}
