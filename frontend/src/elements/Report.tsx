import type { Issue as IssuePart, Report as ReportPart } from "../generated/schemas";
import { Code } from "./Code";
import { Graph } from "./Graph";
import { Issues } from "./Issue";
import { Next } from "./Next";
import { Table } from "./Table";
import { Text } from "./Text";
import "./Report.css";

// A result as a person reads it (web.md § 7.7): its report's blocks in order — a line, a code
// block, a table, a graph, a heading with the actions under it — then its findings. The one renderer
// of every result: no operation has code of its own here.

export function Report({ report, issues = [] }: { report?: ReportPart | null; issues?: IssuePart[] }) {
  return (
    <div className="report">
      {(report?.blocks ?? []).map((block, n) => (
        block.kind === "text" ? <Text key={n} block={block} />
          : block.kind === "code" ? <Code key={n} block={block} />
          : block.kind === "table" ? <Table key={n} table={block} />
          : block.kind === "graph" ? <div key={n} className="report__graph"><Graph graph={block} /></div>
          : <Next key={n} block={block} />
      ))}
      <Issues issues={issues} />
    </div>
  );
}
