// A result that carries no report yet, shown from its JSON alone: each field — a list of rows as
// a table, a record as a list of fields, an action as that action, anything else as text. Its
// findings are drawn by the finding element, as a report's are.

import type { Issue } from "./generated/schemas";
import { ActionButton } from "./elements/ActionButton";
import { Finding } from "./elements/Finding";
import { shown } from "./elements/Table";
import { isAction } from "./kernel/action";

export function Findings({ issues }: { issues?: Issue[] }) {
  if (!issues?.length) return null;
  return <div className="findings">{issues.map((i, n) => <Finding key={n} issue={i} />)}</div>;
}

function isRow(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

export function Value({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (isAction(value)) return <ActionButton action={value} small />;
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="muted">none</span>;
    if (value.every(isAction)) return <span className="next">{value.map((a, n) => <ActionButton key={n} action={a} small />)}</span>;
    if (value.every(isRow)) {
      const columns = Array.from(new Set(value.flatMap((r) => Object.keys(r))));
      return (
        <div className="table-wrap">
          <table>
            <thead><tr>{columns.map((c) => <th key={c}>{c.replace(/_/g, " ")}</th>)}</tr></thead>
            <tbody>
              {value.map((row, n) => (
                <tr key={n}>{columns.map((c) => (
                  <td key={c}>{isRow(row[c]) || Array.isArray(row[c]) ? <Value value={row[c]} depth={depth + 1} /> : shown(row[c])}</td>
                ))}</tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    return <span>{shown(value)}</span>;
  }
  if (isRow(value)) {
    const entries = Object.entries(value).filter(([k]) => k !== "issues" && k !== "plan");
    return (
      <dl className={depth ? "nested" : ""}>
        {entries.map(([k, v]) => (
          <div className="pair" key={k}>
            <dt>{k.replace(/_/g, " ")}</dt>
            <dd>{isRow(v) || Array.isArray(v) ? <Value value={v} depth={depth + 1} /> : shown(v)}</dd>
          </div>
        ))}
      </dl>
    );
  }
  return <span>{shown(value)}</span>;
}
