import type { Table as TablePart } from "../generated/schemas";
import { isAction } from "../kernel/action";
import { useSaying } from "../kernel/declared";
import { ActionButton } from "./ActionButton";
import { Help } from "./Help";
import "./Table.css";

// A table (web.md §§ 7.5, 9.2): its columns named, each with its help on its head; a cell holds a
// value, or an action — the row's own next step, drawn as that action.

export function Table({ table }: { table: TablePart }) {
  const none = useSaying("none");
  return (
    <div className="table">
      <table>
        <thead><tr>{table.columns.map((c) => <th key={c.key}>{c.label}<Help help={c.help} /></th>)}</tr></thead>
        <tbody>{table.rows.map((row, n) => (
          <tr key={n}>{table.columns.map((c) => <td key={c.key}><Cell value={row[c.key]} none={none} /></td>)}</tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function Cell({ value, none }: { value: unknown; none: string }) {
  return isAction(value) ? <ActionButton action={value} /> : <>{shown(value, none)}</>;
}

/** A value as a person reads it: none as the declaration's word for none, a list as its items, a
 *  record as its JSON, else its text. */
function shown(v: unknown, none: string): string {
  if (v === null || v === undefined || v === "") return none;
  if (Array.isArray(v)) return v.map((x) => shown(x, none)).join(", ");
  return typeof v === "object" ? JSON.stringify(v) : String(v);
}
