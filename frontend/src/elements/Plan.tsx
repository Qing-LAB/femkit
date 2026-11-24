import type { Issue } from "../generated/schemas";
import { Finding } from "./Finding";
import "./Plan.css";

// A plan's steps, and the findings a person should know before applying it (web.md § 9.2).

export function Plan({ plan }: { plan: { steps: { id: string; describe: string }[]; issues?: Issue[] } }) {
  return (
    <div className="plan">
      {plan.steps.length === 0 ? <p className="plan__none">Nothing to do.</p> : (
        <ol className="plan__steps">{plan.steps.map((s) => <li key={s.id}>{s.describe}</li>)}</ol>
      )}
      {(plan.issues ?? []).map((i, n) => <Finding key={n} issue={i} quiet />)}
    </div>
  );
}
