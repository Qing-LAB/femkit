// A result, shown from its JSON alone: findings first, then each field — a list of rows as a
// table, a record as a list of fields, anything else as text.

export function Findings({ issues }: { issues: any[] }) {
  if (!issues?.length) return null;
  return (
    <ul className="findings">
      {issues.map((i, n) => (
        <li key={n} className={`finding ${i.severity}`}>
          <span className="severity">{i.severity}</span>
          <span className="message">{i.message}</span>
          {i.next?.length > 0 && <pre className="next">{i.next.join("\n")}</pre>}
        </li>
      ))}
    </ul>
  );
}

function isRow(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function scalar(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "yes" : "no";
  return typeof v === "object" ? JSON.stringify(v) : String(v);
}

export function Value({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (Array.isArray(value)) {
    if (value.length === 0) return <span className="muted">none</span>;
    if (value.every(isRow)) {
      const columns = Array.from(new Set(value.flatMap((r) => Object.keys(r))));
      return (
        <div className="table-wrap">
          <table>
            <thead><tr>{columns.map((c) => <th key={c}>{c.replace(/_/g, " ")}</th>)}</tr></thead>
            <tbody>
              {value.map((row, n) => (
                <tr key={n}>{columns.map((c) => (
                  <td key={c}>{isRow(row[c]) || Array.isArray(row[c]) ? <Value value={row[c]} depth={depth + 1} /> : scalar(row[c])}</td>
                ))}</tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    return <span>{value.map(scalar).join(", ")}</span>;
  }
  if (isRow(value)) {
    const entries = Object.entries(value).filter(([k]) => k !== "issues" && k !== "plan");
    return (
      <dl className={depth ? "nested" : ""}>
        {entries.map(([k, v]) => (
          <div className="pair" key={k}>
            <dt>{k.replace(/_/g, " ")}</dt>
            <dd>{isRow(v) || Array.isArray(v) ? <Value value={v} depth={depth + 1} /> : scalar(v)}</dd>
          </div>
        ))}
      </dl>
    );
  }
  return <span>{scalar(value)}</span>;
}
