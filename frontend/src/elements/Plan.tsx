import type { Issue as IssuePart, PlanAnswer, Report as ReportPart } from "../generated/schemas";
import { useSaying } from "../kernel/declared";
import { Issues } from "./Issue";
import { Report } from "./Report";
import "./Plan.css";

// A plan (web.md §§ 7.7, 9.2): its steps, each with the command it runs; what a person should know
// before agreeing; and, where its operation foresees one, the report its outcome would show — the
// Preview, never shown as done.

export function Plan({ answer }: { answer: PlanAnswer }) {
  const plan = answer.plan;
  const says = { steps: useSaying("steps"), preview: useSaying("preview"), nothing: useSaying("nothing-to-do") };
  const preview = (plan.report as ReportPart).blocks.length > 0;
  return (
    <div className="plan">
      <h4 className="plan__heading">{says.steps}</h4>
      {plan.steps.length === 0 ? <p className="plan__none">{says.nothing}</p> : (
        <ol className="plan__steps">
          {plan.steps.map((s) => (
            <li key={s.id} className="plan__step">
              <span>{s.describe}</span>
              {s.argv && <code className="plan__argv">{s.argv.join(" ")}</code>}
            </li>
          ))}
        </ol>
      )}
      <Issues issues={plan.issues as IssuePart[]} />
      {preview && (
        <section className="plan__preview">
          <h4 className="plan__heading">{says.preview}</h4>
          <Report report={plan.report as ReportPart} />
        </section>
      )}
    </div>
  );
}
