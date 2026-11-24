// The TOML codec (web.md § 7.3): a value as a TOML inline value, both ways. Every value a person
// writes into a file travels as its TOML text, so a decimal stays the text it was typed as; a
// number is held as its text here, never as a binary float.

export class Num {
  constructor(public readonly text: string) {}
}

export type Value = string | boolean | Num | Value[] | { [key: string]: Value };

const BARE = /^[A-Za-z0-9_-]+$/;
const NUMBER = /^[+-]?(\d[\d_]*)(\.\d[\d_]*)?([eE][+-]?\d+)?$|^[+-]?(inf|nan)$/;

export function isNumber(text: string): boolean {
  return NUMBER.test(text.trim());
}

/** ``value`` as a TOML inline value. */
export function write(value: Value): string {
  if (value instanceof Num) return value.text;
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "string") return JSON.stringify(value);   // a TOML basic string escapes as JSON does
  if (Array.isArray(value)) return "[" + value.map(write).join(", ") + "]";
  const pairs = Object.entries(value).map(([k, v]) => `${BARE.test(k) ? k : JSON.stringify(k)} = ${write(v)}`);
  return pairs.length ? "{ " + pairs.join(", ") + " }" : "{}";
}

/** A TOML inline value read: what `write` writes, and what a file's value is. */
export function read(text: string): Value {
  let at = 0;
  const fail = (why: string): never => { throw new Error(`${why} at ${at} of ${JSON.stringify(text)}`); };
  const space = () => { while (at < text.length && /[ \t\r\n]/.test(text[at])) at++; };
  const value = (): Value => {
    space();
    const c = text[at];
    if (c === '"') return basic();
    if (c === "'") { const end = text.indexOf("'", at + 1); if (end < 0) fail("an unclosed string"); const s = text.slice(at + 1, end); at = end + 1; return s; }
    if (c === "[") return list();
    if (c === "{") return table();
    const m = /^[^,\]}\s]+/.exec(text.slice(at));
    if (!m) return fail("a value expected");
    at += m[0].length;
    if (m[0] === "true" || m[0] === "false") return m[0] === "true";
    if (isNumber(m[0])) return new Num(m[0]);
    return fail(`not a value: ${m[0]}`);
  };
  const basic = (): string => {
    let end = at + 1;
    while (end < text.length && text[end] !== '"') end += text[end] === "\\" ? 2 : 1;
    if (end >= text.length) fail("an unclosed string");
    const s = JSON.parse(text.slice(at, end + 1));
    at = end + 1;
    return s;
  };
  const list = (): Value[] => {
    at++;
    const out: Value[] = [];
    for (;;) {
      space();
      if (text[at] === "]") { at++; return out; }
      out.push(value());
      space();
      if (text[at] === ",") at++;
      else if (text[at] !== "]") fail("`,` or `]` expected");
    }
  };
  const key = (): string => {
    space();
    if (text[at] === '"') return basic();
    const m = /^[A-Za-z0-9_-]+/.exec(text.slice(at));
    if (!m) return fail("a key expected");
    at += m[0].length;
    return m[0];
  };
  const table = (): { [k: string]: Value } => {
    at++;
    const out: { [k: string]: Value } = {};
    space();
    if (text[at] === "}") { at++; return out; }
    for (;;) {
      const k = key();
      space();
      if (text[at] !== "=") fail("`=` expected");
      at++;
      out[k] = value();
      space();
      if (text[at] === ",") { at++; continue; }
      if (text[at] === "}") { at++; return out; }
      fail("`,` or `}` expected");
    }
  };
  const result = value();
  space();
  if (at !== text.length) fail("text after the value");
  return result;
}
