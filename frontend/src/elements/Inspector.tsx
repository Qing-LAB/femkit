import { lazy, Suspense, useState, type ReactNode } from "react";
import type { Graph as GraphPart, GraphNode, Issue as IssuePart } from "../generated/schemas";
import { iconOf, useDeclared } from "../kernel/declared";
import { Actions } from "./ActionButton";
import { Badge } from "./Badge";
import { Fact } from "./Fact";
import { Icon } from "./Icon";
import { Issues, OpenIssue } from "./Issue";
import { Tabs } from "./Tabs";
import "./Inspector.css";

// The selected node (web.md §§ 2.2, 9.2): its kind and state; its next steps; its findings — a
// part's with its objects'; what its operation says of it; its files' text in the text editor, each
// finding at its line — an object's its part's, the node its `part` names — its own file with the
// help of every key it may hold; its ports, a stage's outputs with the lines that open them; and what
// it is made from, each leading there.

// The text editor and its library, read when a node's text is first shown, not with the page.
const TextEditor = lazy(() => import("./TextEditor").then((m) => ({ default: m.TextEditor })));

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="inspector__section">
      <h4 className="inspector__heading">{title}</h4>
      {children}
    </section>
  );
}

export function Inspector({ node, graph, lead }: { node: GraphNode; graph: GraphPart; lead?: (address: string) => void }) {
  const { page } = useDeclared();
  const says = page.says;
  const part = node.part ? graph.nodes.find((n) => n.address === node.part) : undefined;
  const owner = part ?? node;
  const files = owner.files.filter((f) => f.text !== null);
  const issues = node.part ? node.issues : graph.nodes.filter((n) => n.address === node.address || n.part === node.address)
    .flatMap((n) => n.issues);
  const [file, setFile] = useState<string | undefined>(undefined);
  const [line, setLine] = useState<number | null>(null);
  const shown = files.find((f) => f.address === file) ?? files[0];
  const open = (issue: IssuePart) => {          // a finding opened here: its file shown, at its line
    const at = files.find((f) => f.path === issue.file);
    if (at) { setFile(at.address); setLine(issue.line); }
  };
  return (
    <div className="inspector" data-shows={node.shows ?? undefined}>
      <header className="inspector__head">
        <span className="inspector__icon"><Icon name={iconOf(page, node)} size="lg" /></span>
        <div className="inspector__words">
          <span className="inspector__kind">{node.type ? `${node.kind} · ${node.type}` : node.kind}</span>
          <h3 className="inspector__label">{node.label}</h3>
          <code className="inspector__address">{node.address}</code>
        </div>
        {node.state && <Badge toned={!!node.shows}>{node.state}</Badge>}
      </header>
      {node.actions.length > 0 && <Section title={says.actions}><Actions actions={node.actions} /></Section>}
      {issues.length > 0 && (
        <Section title={says.issues}><OpenIssue.Provider value={open}><Issues issues={issues} /></OpenIssue.Provider></Section>
      )}
      {node.facts.length > 0 && (
        <Section title={says.facts}>
          <dl className="inspector__facts">{node.facts.map((f) => <Fact key={f.label} fact={f} />)}</dl>
        </Section>
      )}
      {shown && (
        <Section title={says.files}>
          {files.length > 1 && (
            <Tabs quiet label={says.files} chosen={shown.address} choose={setFile}
                  tabs={files.map((f) => ({ key: f.address, label: f.path.split("/").pop() ?? f.path, title: f.path }))} />
          )}
          <Suspense fallback={<p className="inspector__loading">{says.loading}</p>}>
            <TextEditor key={shown.address} file={shown} keys={shown.address === owner.address ? owner.keys : []}
                        issues={issues} line={line} />
          </Suspense>
        </Section>
      )}
      {node.ports.length > 0 && (
        <Section title={says.ports}>
          <ul className="inspector__ports">
            {node.ports.map((p) => (
              <li key={`${p.side}:${p.name}`} className={`inspector__port inspector__port--${p.side}`}>
                <span className="inspector__port-name">{p.name}</span>
                <span className="inspector__port-type">{p.accepts.join(" | ")}</span>
                {p.names.length > 0 && <span className="inspector__port-names">{p.names.join(", ")}</span>}
                {p.file && <code className="inspector__port-file">{p.file}</code>}
                {p.actions.length > 0 && <Actions actions={p.actions} />}
              </li>
            ))}
          </ul>
        </Section>
      )}
      {node.made_from.length > 0 && (
        <Section title={says["made-from"]}>
          <ul className="inspector__made">
            {node.made_from.map((m) => (
              <li key={m}>
                {lead ? <button type="button" className="inspector__lead" onClick={() => lead(m)}>{m}</button> : <code>{m}</code>}
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}
