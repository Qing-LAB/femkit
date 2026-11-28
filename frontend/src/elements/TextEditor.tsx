import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  autocompletion, closeBrackets, closeBracketsKeymap, completionKeymap, type Completion, type CompletionContext,
  type CompletionResult,
} from "@codemirror/autocomplete";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import {
  bracketMatching, foldGutter, foldKeymap, foldService, indentOnInput, StreamLanguage, syntaxHighlighting,
} from "@codemirror/language";
import { python } from "@codemirror/lang-python";
import { toml } from "@codemirror/legacy-modes/mode/toml";
import { lintKeymap, setDiagnostics, type Diagnostic } from "@codemirror/lint";
import { highlightSelectionMatches, search, searchKeymap } from "@codemirror/search";
import { Annotation, Compartment, EditorState, StateEffect, StateField, type Extension, type Range } from "@codemirror/state";
import {
  Decoration, type DecorationSet, drawSelection, EditorView, highlightActiveLine, highlightActiveLineGutter,
  highlightSpecialChars, hoverTooltip, keymap, lineNumbers, WidgetType,
} from "@codemirror/view";
import { classHighlighter } from "@lezer/highlight";
import type { Field, File, Issue as IssuePart } from "../generated/schemas";
import { actOf, TONE } from "../kernel/action";
import { useDeclared } from "../kernel/declared";
import { changed } from "../kernel/document";
import { forget, keep, languageOf, type Language, useEdit } from "../kernel/editor";
import { open as openFlow } from "../kernel/flows";
import { useMarks } from "../kernel/marks";
import { pieces } from "../kernel/sentence";
import { adopting } from "../kernel/styles";
import { keyAt, tableFold, type KeyPlace } from "../kernel/toml";
import { kindOf, optional, type Schema } from "../kernel/schema";
import { Badge } from "./Badge";
import { Button } from "./Button";
import { Issues } from "./Issue";
import { Key, written } from "./Key";
import "./TextEditor.css";

// A file's text (web.md § 9.2; ADR 0024): one element on CodeMirror 6, through this thin wrapper of
// the page's own — read-only where the file is shown, editable where the person edits it, by the
// save its file carries. Read in the language the declaration names for the file's name; its colours
// the tokens'. Each finding the server gives is at its line and key: the key underlined, the line
// marked by its severity, its sentence and what would be right beneath it — CodeMirror's diagnostics,
// fed the findings as they are. Each key's help on hover, and the keys the file may hold and each
// key's allowed values offered as the person types — all from the node's keys alone; nothing is
// typed for them, and the text is exactly what was typed. Search, line numbers, folding and the
// keyboard are CodeMirror's own, and its undo while typing; femkit never undoes a saved file. The
// save is the file's own action, carried through the action machine docked beside the workspaces:
// its plan — the change's impact — shown first and marked on the diagrams, applied with its digest.

/** The languages the editor carries, by the declaration's names: each one's reading of a text. */
const LANGUAGES: Record<Language, () => Extension> = {
  toml: () => [StreamLanguage.define(toml), foldService.of((state, from, to) => tableFold(state.doc.toString(), from, to))],
  python: () => python(),
};

/** How many tips have been shown: each one's name, for the page's own drawing of it. */
let tipped = 0;

/** A text replaced from the server — the file read again — which is no typing of the person's. */
const read = Annotation.define<boolean>();

/** The findings beneath their lines, each line marked by its severity: given whole each time. */
const setNotes = StateEffect.define<{ line: number; severity: string; box: HTMLElement }[]>();

class Note extends WidgetType {
  constructor(readonly box: HTMLElement) { super(); }
  eq(other: Note) { return other.box === this.box; }
  toDOM() { return this.box; }
  ignoreEvent() { return true; }
}

const notes = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(set, tr) {
    let next = set.map(tr.changes);
    for (const e of tr.effects) {
      if (!e.is(setNotes)) continue;
      const ranges: Range<Decoration>[] = [];
      for (const n of e.value) {
        if (n.line > tr.state.doc.lines) continue;
        const line = tr.state.doc.line(n.line);
        ranges.push(Decoration.line({ class: "editor__found", attributes: { "data-severity": n.severity } }).range(line.from));
        ranges.push(Decoration.widget({ widget: new Note(n.box), block: true, side: 1 }).range(line.to));
      }
      next = Decoration.set(ranges, true);
    }
    return next;
  },
  provide: (f) => EditorView.decorations.from(f),
});

/** The keys of ``keys`` a path names: a key's `*` stands for a name the person chooses. */
function named(keys: Field[], path: string[]): Field | undefined {
  return keys.find((k) => {
    const steps = (k.key ?? "").split(".");
    return steps.length === path.length && steps.every((s, i) => s === "*" || s === path[i]);
  });
}

/** The keys one step under ``parent`` — those a table at it may hold. */
function under(keys: Field[], parent: string[]): Field[] {
  return keys.filter((k) => {
    const steps = (k.key ?? "").split(".");
    return steps.length === parent.length + 1 && parent.every((p, i) => steps[i] === "*" || steps[i] === p);
  });
}

/** Whether a key's fragment is a table — a record, a map of named tables, or a list of records. */
function isTable(k: Field): boolean {
  const s = k.json_schema as Schema;
  const kind = kindOf(optional(s, s).inner, s);
  return kind === "record" || kind === "map" || (kind === "list" && kindOf(optional(s, s).inner.items ?? {}, s) === "record");
}

/** Where a finding stands on its line: its key's last step, where the line writes it; else the line. */
function spot(state: EditorState, issue: IssuePart): { from: number; to: number } | null {
  if (!issue.line || issue.line > state.doc.lines) return null;
  const line = state.doc.line(issue.line);
  const last = issue.key?.split(".").pop();
  const found = last ? new RegExp(`(^|[^\\w-])(${last.replace(/[\\^$.*+?()[\]{}|]/g, "\\$&")})(?![\\w-])`).exec(line.text) : null;
  if (found) {
    const at = found.index + found[1].length;
    return { from: line.from + at, to: line.from + at + found[2].length };
  }
  const lead = line.text.length - line.text.trimStart().length;
  return { from: line.from + lead, to: Math.max(line.from + lead, line.to) };
}

/** A sentence of the server's as the diagnostics' own tooltip shows it: its code as code. */
function said(text: string): Node {
  const out = document.createElement("span");
  for (const p of pieces(text)) {
    const part = document.createElement(p.code ? "code" : "span");
    part.textContent = p.text;
    out.append(part);
  }
  return out;
}

export function TextEditor({ file, keys = [], issues, line }: {
  file: File; keys?: Field[]; issues: IssuePart[]; line?: number | null;
}) {
  const { page, operations } = useDeclared();
  const controls = page.controls;
  const edit = useEdit(file.address);
  const marks = useMarks();
  const [editing, setEditing] = useState(false);
  const [tips, setTips] = useState<Map<HTMLElement, Field>>(new Map());
  const holder = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const writable = useRef(new Compartment());
  const language = languageOf(page.editor, file.path);
  const opened = edit?.opened ?? file;
  const writing = !!opened.save && (editing || !!edit);
  const save = opened.save ? actOf(opened.save, operations) : null;

  // What the callbacks CodeMirror holds read now.
  const now = useRef({ file, keys, writing, opened });
  now.current = { file, keys, writing, opened };

  // The findings shown: a plan's on this file — the change's impact, on the text typed — while one is
  // shown for it; else the file's own.
  const planned = writing ? marks.issues.filter((i) => i.file === file.path) : [];
  const shown = (planned.length ? planned : issues).filter((i) => i.file === file.path && i.line !== null);
  const groups = useMemo(() => {
    const at = new Map<number, IssuePart[]>();
    for (const i of shown) at.set(i.line!, [...(at.get(i.line!) ?? []), i]);
    return [...at.entries()];
  }, [JSON.stringify(shown)]);
  const boxes = useRef(new Map<string, HTMLElement>());
  const placed = groups.map(([n, found]) => {
    const name = `${n}\u0000${found.map((i) => i.code + i.message).join("\u0000")}`;
    if (!boxes.current.has(name)) {
      const box = document.createElement("div");
      box.className = "editor__note";
      boxes.current.set(name, box);
    }
    return { name, line: n, found, box: boxes.current.get(name)! };
  });
  for (const name of [...boxes.current.keys()]) if (!placed.some((p) => p.name === name)) boxes.current.delete(name);

  useEffect(() => {
    const show = (dom: HTMLElement, field: Field) => {
      dom.dataset.tip = String(++tipped);
      setTips((t) => new Map(t).set(dom, field));
      return { dom, destroy: () => setTips((t) => { const n = new Map(t); n.delete(dom); return n; }) };
    };
    const keyed = () => now.current.keys.length > 0;

    const hover = hoverTooltip((v, pos) => {
      if (!keyed()) return null;
      const place = keyAt(v.state.doc.toString(), pos);
      const field = place && place.side !== "value" ? named(now.current.keys, place.path) : undefined;
      if (!place || !field) return null;
      return { pos: place.from, end: place.to, above: true, create: () => show(document.createElement("div"), field) };
    });

    const complete = (context: CompletionContext): CompletionResult | null => {
      if (!now.current.writing || !keyed()) return null;
      const place: KeyPlace | null = keyAt(context.state.doc.toString(), context.pos);
      if (!place) return null;
      const keysNow = now.current.keys;
      const info = (field: Field) => () => show(document.createElement("div"), field);
      let options: Completion[] = [];
      if (place.side === "value") {
        const field = named(keysNow, place.path);
        if (!field) return null;
        const s = optional(field.json_schema as Schema, field.json_schema as Schema).inner;
        const values = s.enum ?? (s.type === "boolean" ? [true, false] : []);
        options = (values as unknown[]).map((v) => ({ label: written(v), type: "enum", info: info(field) }));
      } else {
        const parent = place.path.slice(0, -1);
        options = under(keysNow, parent).filter((k) => (place.side === "table") === isTable(k)).map((k) => {
          const name = (k.key ?? "").split(".").pop()!;
          return { label: name === "*" ? k.label : name, type: place.side === "table" ? "namespace" : "property",
                   detail: k.required ? undefined : page.says.optional, info: info(k) };
        });
      }
      if (!options.length || (!context.explicit && place.from === context.pos && place.side !== "value")) return null;
      return { from: place.from, options, validFor: /^[\w"'-]*$/ };
    };

    const state = EditorState.create({
      doc: edit?.text ?? file.text ?? "",
      extensions: [
        lineNumbers(), foldGutter(), highlightActiveLineGutter(), highlightSpecialChars(), history(), drawSelection(),
        indentOnInput(), bracketMatching(), closeBrackets(), highlightActiveLine(), highlightSelectionMatches(),
        search({ top: true }), autocompletion({ override: [complete] }), EditorView.lineWrapping,
        keymap.of([...closeBracketsKeymap, ...defaultKeymap, ...searchKeymap, ...historyKeymap, ...foldKeymap,
                   ...completionKeymap, ...lintKeymap]),
        syntaxHighlighting(classHighlighter),
        language ? LANGUAGES[language]() : [],
        writable.current.of(EditorState.readOnly.of(true)),
        notes, hover,
        EditorView.contentAttributes.of({ "aria-label": file.path }),
        EditorView.updateListener.of((u) => {
          if (!u.docChanged || u.transactions.some((tr) => tr.annotation(read))) return;
          const typed = u.state.doc.toString();
          const base = now.current.opened;
          if (typed === base.text) forget(base.address); else keep(base, typed);
        }),
      ],
    });
    view.current = adopting(() => new EditorView({ state, parent: holder.current! }));
    return () => { view.current?.destroy(); view.current = null; };
  }, [file.address, language]);

  // Written while the person edits; read where it is shown — focused, searched and moved through by
  // the keyboard either way.
  useEffect(() => {
    view.current?.dispatch({ effects: writable.current.reconfigure(EditorState.readOnly.of(!writing)) });
  }, [writing, file.address, language]);

  // The file read again — saved, or changed and reloaded — replaces the text where nothing typed waits.
  useEffect(() => {
    const v = view.current;
    if (!v || edit || v.state.doc.toString() === (file.text ?? "")) return;
    v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: file.text ?? "" }, annotations: read.of(true) });
  }, [file.sha256, file.text, !!edit]);

  // Each finding at its line and key, its sentence beneath.
  useEffect(() => {
    const v = view.current;
    if (!v) return;
    const diagnostics: Diagnostic[] = shown.flatMap((i) => {
      const at = spot(v.state, i);
      return at ? [{ ...at, severity: i.severity, message: i.message, renderMessage: () => said(i.message) }] : [];
    });
    v.dispatch(setDiagnostics(v.state, diagnostics));
    v.dispatch({ effects: setNotes.of(placed.map((p) => ({ line: p.line, severity: p.found[0].severity, box: p.box }))) });
  }, [groups, file.address, language]);

  // A finding opened elsewhere: its line in view.
  useEffect(() => {
    const v = view.current;
    if (!v || !line || line > v.state.doc.lines) return;
    const at = v.state.doc.line(line).from;
    v.dispatch({ selection: { anchor: at }, effects: EditorView.scrollIntoView(at, { y: "center" }) });
  }, [line, file.address]);

  const typed = edit?.text;
  const begin = () => { setEditing(true); requestAnimationFrame(() => view.current?.focus()); };
  const reload = () => { forget(file.address); setEditing(true); changed(); };
  const press = () => {
    if (!save || typed === undefined) return;
    const text = save.fills[0];
    openFlow(save, { values: text ? { [text.field]: typed } : {}, docked: true,
                     done: (ok) => { if (ok) forget(file.address); } });
  };
  return (
    <div className="editor" data-writing={writing || undefined}>
      <div className="editor__head">
        <span className="editor__path">{file.path}</span>
        {edit && <Badge>{page.says.edited}</Badge>}
        {opened.save && !writing && (
          <Button small icon={controls.edit.icon} title={controls.edit.help} onClick={begin}>{controls.edit.label}</Button>
        )}
        {writing && (
          <Button small bare icon={controls.reload.icon} title={controls.reload.help} onClick={reload}>{controls.reload.label}</Button>
        )}
        {writing && save && (
          <span className="editor__save" data-group={save.operation.group}>
            <Button small tone={TONE[save.operation.effect as keyof typeof TONE]} disabled={typed === undefined}
                    title={opened.save!.help?.sentence ?? opened.save!.command} onClick={press}>{save.label}</Button>
          </span>
        )}
      </div>
      <div className="editor__body" ref={holder} />
      {placed.map((p) => createPortal(<Issues issues={p.found} />, p.box, p.name))}
      {[...tips.entries()].map(([dom, field]) => createPortal(<Key field={field} />, dom, dom.dataset.tip))}
    </div>
  );
}
