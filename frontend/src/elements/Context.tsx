import { useEffect } from "react";
import type { ContextPart } from "../generated/schemas";
import { useChoices } from "../kernel/choices";
import { useDeclared } from "../kernel/declared";
import { go, usePage } from "../kernel/state";
import "./Context.css";

// A context's chooser, and the bar of them (web.md §§ 2.2, 8.1, 9.4): a chooser for each context the workspace in view
// needs, or its document's request takes — each its label and help, its choices the operation the
// declaration names; a context waits until what it depends on is chosen. A context the person need
// not choose is not asked: one with a single choice is chosen; one the request holds a default for
// shows that default (`unset`) until another is chosen.

export function Chooser({ part, hero }: { part: ContextPart; hero?: boolean }) {
  const { page } = useDeclared();
  const state = usePage();
  const choices = useChoices(part, state);
  const waiting = part.depends.some((d) => !state[d]);
  const only = !state[part.key] && !waiting && choices?.length === 1 ? choices[0].value : null;
  useEffect(() => { if (only) go({ [part.key]: only }, page.context, true); }, [only]);
  return (
    <label className={`context ${hero ? "context--hero" : ""}`} title={part.help}>
      <span className="context__label">{part.label}</span>
      <select className="context__choice" value={state[part.key] ?? ""} disabled={waiting || !choices}
              onChange={(e) => go({ [part.key]: e.target.value }, page.context)}>
        <option value="">{part.unset ?? page.controls.select.label}</option>
        {(choices ?? []).map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
      </select>
    </label>
  );
}

export function ContextBar({ parts }: { parts: ContextPart[] }) {
  if (!parts.length) return null;
  return <div className="context__bar">{parts.map((p) => <Chooser key={p.key} part={p} />)}</div>;
}
