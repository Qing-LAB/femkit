import type { Issue, Report as ReportPart } from "../generated/schemas";
import { ActionButton } from "./ActionButton";
import { Finding } from "./Finding";
import { Table } from "./Table";
import "./Report.css";

// A result as a person reads it (web.md § 7.6): its report's blocks in order — a line, a table,
// a heading with the actions under it — then its findings. The one renderer of every result: no
// operation has code of its own here.

export function Report({ result }: { result: { report?: ReportPart | null; issues?: Issue[] } }) {
  return (
    <div className="report">
      {(result.report?.blocks ?? []).map((block, n) => (
        block.kind === "text" ? <p key={n} className="report__text">{block.text}</p>
          : block.kind === "table" ? <Table key={n} table={block} />
          : (
            <div key={n} className="report__next">
              <h3 className="report__label">{block.label}</h3>
              <div className="report__actions">{block.actions.map((a, i) => <ActionButton key={i} action={a} small />)}</div>
            </div>
          )
      ))}
      {(result.issues ?? []).map((issue, n) => <Finding key={n} issue={issue} />)}
    </div>
  );
}
