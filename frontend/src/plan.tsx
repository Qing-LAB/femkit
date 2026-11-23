import { useState } from "react";
import { apply, lines, NeedToken, planOperation, Refused } from "./api";
import { Findings } from "./Value";

// One change through plan and apply (api.md § 5.2): the plan is shown, then applied with the
// digest of the plan shown; the findings it leaves are shown, never refused.

export interface Change { operation: string; request: Record<string, unknown>; title: string }

export function PlanApply({ change, onDone, onCancel }: {
  change: Change; onDone: () => void; onCancel: () => void;
}) {
  const [state, setState] = useState<{ kind: string; plan?: any; digest?: string; message?: string; next?: string[];
                                       outcome?: any }>({ kind: "idle" });
  const plan = async () => {
    setState({ kind: "planning" });
    try {
      const { plan, digest } = await planOperation(change.operation, change.request);
      setState({ kind: "planned", plan, digest });
    } catch (e) {
      if (e instanceof NeedToken) return setState({ kind: "refused", message: "the token is missing" });
      setState({ kind: "refused", message: e instanceof Refused ? e.message : String(e),
                 next: e instanceof Refused ? e.next : [] });
    }
  };
  const go = async () => {
    setState((s) => ({ ...s, kind: "applying" }));
    try {
      for await (const line of lines(await apply(change.operation, change.request, state.digest!))) {
        if (line.refused || line.defect) {
          return setState({ kind: "refused", message: line.message, next: line.next ?? [] });
        }
        if (line.ok === false) {          // the last line: an outcome that did not end well stays on screen
          return setState({ kind: "failed", outcome: line.outcome });
        }
      }
      onDone();
    } catch (e) {
      setState({ kind: "refused", message: e instanceof Refused ? e.message : String(e) });
    }
  };
  return (
    <div className="change">
      <div className="change-title">{change.title}</div>
      {state.kind === "idle" && <div className="actions"><button onClick={plan}>Plan</button>
        <button className="quiet" onClick={onCancel}>Cancel</button></div>}
      {state.kind === "planning" && <p className="muted">Planning…</p>}
      {(state.kind === "planned" || state.kind === "applying") && state.plan && (
        <>
          <ol className="plan-steps">{state.plan.steps.map((s: any) => <li key={s.id}>{s.describe}</li>)}</ol>
          {state.plan.steps.length === 0 && <p className="muted">Nothing changes.</p>}
          <Findings issues={state.plan.issues} />
          <div className="actions">
            <button onClick={go} disabled={state.kind === "applying"}>{state.kind === "applying" ? "Applying…" : "Apply"}</button>
            <button className="quiet" onClick={onCancel}>Cancel</button>
          </div>
        </>
      )}
      {state.kind === "failed" && (
        <div className="result not-ok">
          <p>{state.outcome?.status === "failed" ? "A step failed." : "It ended with findings."}</p>
          <Findings issues={state.outcome?.issues ?? []} />
          {state.outcome?.log && <p className="muted">The operation's log: <code>{state.outcome.log}</code></p>}
          <div className="actions"><button className="quiet" onClick={onDone}>Close</button></div>
        </div>
      )}
      {state.kind === "refused" && (
        <div className="result not-ok">
          <p>{state.message}</p>
          {state.next && state.next.length > 0 && <pre className="next">{state.next.join("\n")}</pre>}
          <div className="actions"><button className="quiet" onClick={onCancel}>Close</button></div>
        </div>
      )}
    </div>
  );
}
