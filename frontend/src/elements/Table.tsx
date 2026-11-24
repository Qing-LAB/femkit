import type { Table as TablePart } from "../generated/schemas";
import { isAction } from "../kernel/action";
import { ActionButton } from "./ActionButton";
import { Help } from "./Help";
import "./Table.css";

// A table (web.md §§ 7.5, 9.2): its columns named, each with its help on its head — no heads
// where no column is named; a cell holds a value, or an action — the row's own next step, drawn
// as that action.

export function Table({ table }: { table: TablePart }) {
  return (
    <div className="table">
      <table>
        {table.columns.some((c) => c.label) && (
          <thead><tr>{table.columns.map((c) => <th key={c.key}>{c.label} <Help help={c.help} /></th>)}</tr></thead>
        )}
        <tbody>{table.rows.map((row, n) => (
          <tr key={n}>{table.columns.map((c) => <td key={c.key}><Cell value={row[c.key]} /></td>)}</tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function Cell({ value }: { value: unknown }) {
  return isAction(value) ? <ActionButton action={value} small /> : <>{shown(value)}</>;
}

/** A value as a person reads it: none as a dash, a list as its items, a record as its JSON, else
 *  its text. */
export function shown(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) return v.map(shown).join(", ");
  return typeof v === "object" ? JSON.stringify(v) : String(v);
}
