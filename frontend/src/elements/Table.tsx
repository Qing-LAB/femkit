import type { ReactNode } from "react";
import "./Table.css";

// A table (web.md § 9.2): its columns named, each with its help on its head.

export interface Column<R> { key: string; label: string; help?: string; cell?: (row: R) => ReactNode }

export function Table<R extends Record<string, any>>({ columns, rows, keyOf }: {
  columns: Column<R>[]; rows: R[]; keyOf: (row: R) => string;
}) {
  return (
    <div className="table">
      <table>
        <thead><tr>{columns.map((c) => <th key={c.key} title={c.help}>{c.label}</th>)}</tr></thead>
        <tbody>{rows.map((r) => <tr key={keyOf(r)}>{columns.map((c) => <td key={c.key}>{c.cell ? c.cell(r) : String(r[c.key] ?? "—")}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}
