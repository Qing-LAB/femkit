// TOML on the page: a value as the person gave it (web.md § 7.3), written either way a request takes
// it — as its TOML text, where the request takes the value whole as TOML (`Fill.toml`, `config set`'s
// value — the one convention of every value a person writes into a file, so a decimal stays the text
// it was typed as), or as JSON; a number held as its text, never as a binary float — and the key a
// place of a file's text stands at, which the text editor's help and suggestions are found by
// (web.md § 9.2).

export class Num {
  constructor(public readonly text: string) {}
}

export type Value = string | boolean | Num | Value[] | { [key: string]: Value };

const BARE = /^[A-Za-z0-9_-]+$/;


/** ``value`` as a TOML inline value. */
export function write(value: Value): string {
  if (value instanceof Num) return value.text;
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "string") return JSON.stringify(value);   // a TOML basic string escapes as JSON does
  if (Array.isArray(value)) return "[" + value.map(write).join(", ") + "]";
  const pairs = Object.entries(value).map(([k, v]) => `${BARE.test(k) ? k : JSON.stringify(k)} = ${write(v)}`);
  return pairs.length ? "{ " + pairs.join(", ") + " }" : "{}";
}

/** ``value`` as JSON for a request field that takes it whole (web.md § 7.3): a number as the number
 *  its text writes; a list and a record each part so. */
export function json(value: Value): unknown {
  if (value instanceof Num) return Number(value.text);
  if (Array.isArray(value)) return value.map(json);
  if (typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, json(v)]));
  return value;
}

// ------------------------------------------------------------------ the key at a place of a text

/** Where a place of a TOML text stands (web.md § 9.2: each key's help on hover, its allowed values
 *  and the keys the file may hold offered as the person types): the path of the key it is in — from
 *  the file's top, its table's header first, as a finding names a key (`Issue.key`) — whether it is
 *  on the key, its value or a table's header, and the range of the word there. Read line by line: a
 *  value written over several lines is read on its first. */
export interface KeyPlace {
  path: string[];
  side: "key" | "value" | "table";
  from: number;
  to: number;
}

interface Segment { name: string; from: number; to: number }

const BARE_CHAR = /[A-Za-z0-9_-]/;
const HEADER = /^\s*\[\[?/;

/** The dotted key starting at ``i`` of ``line`` — each segment bare or quoted — and where it ends. */
function readKey(line: string, i: number): { segments: Segment[]; end: number } {
  const segments: Segment[] = [];
  for (;;) {
    while (line[i] === " " || line[i] === "\t") i++;
    const from = i;
    let name = "";
    if (line[i] === '"' || line[i] === "'") {
      const quote = line[i++];
      while (i < line.length && line[i] !== quote) { if (quote === '"' && line[i] === "\\") i++; name += line[i++]; }
      if (line[i] === quote) i++;
    } else {
      while (i < line.length && BARE_CHAR.test(line[i])) name += line[i++];
    }
    if (i === from) break;
    segments.push({ name, from, to: i });
    let j = i;
    while (line[j] === " " || line[j] === "\t") j++;
    if (line[j] !== ".") break;
    i = j + 1;
  }
  return { segments, end: i };
}

/** The path of the table a line of ``lines`` stands in: the header above it, none at the top. */
function tableOf(lines: string[], n: number): string[] {
  for (let k = n; k >= 0; k--) {
    const opened = HEADER.exec(lines[k]);
    if (opened) return readKey(lines[k], opened[0].length).segments.map((s) => s.name);
  }
  return [];
}

/** Where the place ``pos`` of ``text`` stands, or none — in a comment, or past what a line reads. */
export function keyAt(text: string, pos: number): KeyPlace | null {
  const start = text.lastIndexOf("\n", pos - 1) + 1;
  const stop = text.indexOf("\n", pos);
  const line = text.slice(start, stop < 0 ? text.length : stop);
  const col = pos - start;
  const lines = text.slice(0, start).split("\n");
  const n = lines.length - 1;
  const opened = HEADER.exec(line);
  if (opened) {
    const { segments } = readKey(line, opened[0].length);
    const at = segments.findIndex((s) => col >= s.from && col <= s.to);
    if (at >= 0) return { path: segments.slice(0, at + 1).map((s) => s.name), side: "table", from: start + segments[at].from, to: start + segments[at].to };
    return col >= opened[0].length && !segments.length ? { path: [""], side: "table", from: pos, to: pos } : null;
  }
  const table = tableOf(lines, n - 1);
  const stack: { inline: boolean; owner: string[] }[] = [];
  let prefix: string[] = [];
  let owner: string[] = [];
  let expectKey = true;
  let i = 0;
  while (i <= line.length) {
    while (line[i] === " " || line[i] === "\t") i++;
    if (line[i] === "#") return null;
    if (expectKey) {
      const { segments, end } = readKey(line, i);
      if (!segments.length) {
        return col === i || (i >= line.length && col >= i) ? { path: [...table, ...prefix, ""], side: "key", from: pos, to: pos } : null;
      }
      const at = segments.findIndex((s) => col >= s.from && col <= s.to);
      if (at >= 0) {
        return { path: [...table, ...prefix, ...segments.slice(0, at + 1).map((s) => s.name)], side: "key",
                 from: start + segments[at].from, to: start + segments[at].to };
      }
      owner = [...prefix, ...segments.map((s) => s.name)];
      i = end;
      while (line[i] === " " || line[i] === "\t") i++;
      if (line[i] !== "=") return null;
      i++;
      expectKey = false;
      continue;
    }
    if (i >= line.length) return col >= i ? { path: [...table, ...owner], side: "value", from: pos, to: pos } : null;
    const c = line[i];
    if (c === "{") { stack.push({ inline: true, owner }); prefix = owner; expectKey = true; i++; continue; }
    if (c === "[") { stack.push({ inline: false, owner }); i++; continue; }
    if (c === "}" || c === "]") {
      stack.pop();
      const top = stack[stack.length - 1];
      prefix = top?.inline ? top.owner : [];
      i++;
      continue;
    }
    if (c === ",") {
      const top = stack[stack.length - 1];
      if (top?.inline) { prefix = top.owner; expectKey = true; } else if (top) owner = top.owner;
      i++;
      continue;
    }
    const from = i;
    if (c === '"' || c === "'") {
      i++;
      while (i < line.length && line[i] !== c) { if (c === '"' && line[i] === "\\") i++; i++; }
      i++;
    } else {
      while (i < line.length && !/[\s,\]}#]/.test(line[i])) i++;
    }
    if (col >= from && col <= i) return { path: [...table, ...owner], side: "value", from: start + from, to: start + i };
  }
  return null;
}

/** The range a table's header at the line ``from``–``to`` of ``text`` folds: the lines after it, up
 *  to the next header, blank lines at its end left out; none where the line is no header. */
export function tableFold(text: string, from: number, to: number): { from: number; to: number } | null {
  if (!HEADER.test(text.slice(from, to))) return null;
  let end = to;
  let at = to;
  while (at < text.length) {
    const next = text.indexOf("\n", at + 1);
    const line = text.slice(at + 1, next < 0 ? text.length : next);
    if (HEADER.test(line)) break;
    if (line.trim()) end = next < 0 ? text.length : next;
    if (next < 0) break;
    at = next;
  }
  return end > to ? { from: to, to: end } : null;
}
