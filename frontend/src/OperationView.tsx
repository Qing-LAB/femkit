import { useEffect, useState } from "react";
import { actionLine, apply, lines, NeedToken, OperationInfo, planOperation, Refused, runOperation } from "./api";
import { Form, requestFrom, Values } from "./Form";
import { Progress } from "./Progress";
import { Findings, Value } from "./Value";
import type { Action } from "./generated/schemas";

// One operation as a form, its plan, its outcome (web.md § 2): a read-only one is run; a
// changing one is planned, shown, and applied with the digest of the plan shown.

type Phase =
  | { kind: "idle" }
  | { kind: "busy"; what: string }
  | { kind: "planned"; plan: any; digest: string; request: unknown }
  | { kind: "applying"; plan: any; runs: string[] }
  | { kind: "done"; ok: boolean; result: any; plan?: any; runs?: string[] }
  | { kind: "refused"; message: string; next: Action[]; kind2: string };

export function command(name: string): string {
  return "python -m femkit " + name.replace(/\./g, " ");
}

export function OperationView({ op, onNeedToken }: { op: OperationInfo; onNeedToken: () => void }) {
  const [values, setValues] = useState<Values>({});
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [problems, setProblems] = useState<string[]>([]);

  useEffect(() => { setValues({}); setPhase({ kind: "idle" }); setProblems([]); }, [op.name]);

  const fail = (e: unknown) => {
    if (e instanceof NeedToken) return onNeedToken();
    if (e instanceof Refused) return setPhase({ kind: "refused", message: e.message, next: e.next, kind2: e.kind });
    setPhase({ kind: "refused", message: String(e), next: [], kind2: "error" });
  };

  const request = () => {
    const { request, problems } = requestFrom(op.request, values);
    setProblems(problems);
    return problems.length ? null : request;
  };

  const run = async () => {
    const req = request();
    if (req === null) return;
    setPhase({ kind: "busy", what: "running" });
    try {
      const { ok, result } = await runOperation(op.name, req);
      setPhase({ kind: "done", ok, result });
    } catch (e) { fail(e); }
  };

  const plan = async () => {
    const req = request();
    if (req === null) return;
    setPhase({ kind: "busy", what: "planning" });
    try {
      const { plan, digest } = await planOperation(op.name, req);
      setPhase({ kind: "planned", plan, digest, request: req });
    } catch (e) { fail(e); }
  };

  const go = async () => {
    if (phase.kind !== "planned") return;
    const { plan, digest, request } = phase;
    const runs: string[] = [];
    setPhase({ kind: "applying", plan, runs });
    try {
      for await (const line of lines(await apply(op.name, request, digest))) {
        if (line.operation) {
          runs.push(line.operation);
          setPhase({ kind: "applying", plan, runs: [...runs] });
        } else if (line.outcome) {
          setPhase({ kind: "done", ok: line.ok, result: line.outcome, plan, runs: [...runs] });
        } else if (line.refused || line.defect) {
          setPhase({ kind: "refused", message: line.message, next: line.next ?? [], kind2: line.refused ?? line.defect });
        }
      }
    } catch (e) { fail(e); }
  };

  const busy = phase.kind === "busy" || phase.kind === "applying";
  return (
    <section className="operation">
      <header>
        <h1>{op.name}</h1>
        <code className="command">{command(op.name)}</code>
        <p className="lead">{op.description}</p>
        <span className={`badge ${op.changes ? "changes" : "reads"}`}>{op.changes ? "changes things" : "reads only"}</span>
      </header>

      <div className="card">
        <h2>Request</h2>
        <Form schema={op.request} values={values} onChange={setValues} disabled={busy} />
        {problems.length > 0 && <ul className="problems">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
        <div className="actions">
          {op.changes
            ? <button onClick={plan} disabled={busy}>{phase.kind === "busy" ? "Planning…" : "Plan"}</button>
            : <button onClick={run} disabled={busy}>{phase.kind === "busy" ? "Running…" : "Run"}</button>}
        </div>
      </div>

      {(phase.kind === "planned" || phase.kind === "applying" || (phase.kind === "done" && phase.plan)) && (
        <div className="card">
          <h2>Plan</h2>
          {(() => {
            const p = phase.kind === "planned" || phase.kind === "applying" ? phase.plan : (phase as any).plan;
            return (
              <>
                {p.steps.length === 0 ? <p className="muted">Nothing to do.</p> : (
                  <ol className="plan-steps">
                    {p.steps.map((s: any) => (
                      <li key={s.id}>
                        <span>{s.describe}</span>
                        {s.argv && <code className="argv">$ {s.argv.join(" ")}</code>}
                      </li>
                    ))}
                  </ol>
                )}
                <Findings issues={p.issues} />
                {p.asks?.length > 0 && (
                  <p className="muted">On a terminal it would ask for: {p.asks.map((a: any) => a.key).join(", ")}.
                    Fill those fields above and plan again.</p>
                )}
              </>
            );
          })()}
          {phase.kind === "planned" && (
            <div className="actions">
              <button className="primary" onClick={go}>Apply this plan</button>
              <button className="quiet" onClick={() => setPhase({ kind: "idle" })}>Discard</button>
            </div>
          )}
        </div>
      )}

      {(phase.kind === "applying" || phase.kind === "done") && (phase as any).runs?.length > 0 && (
        <div className="card">
          <h2>Progress</h2>
          {(phase as any).runs.map((address: string) => (
            <Progress key={address} address={address} steps={(phase as any).plan.steps} />
          ))}
        </div>
      )}

      {phase.kind === "done" && (
        <div className={`card result ${phase.ok ? "ok" : "not-ok"}`}>
          <h2>{op.changes ? "Outcome" : "Result"} <span className={`badge ${phase.ok ? "done" : "failed"}`}>{phase.ok ? "ok" : "not ok"}</span></h2>
          <Findings issues={phase.result.issues} />
          <Value value={phase.result} />
        </div>
      )}

      {phase.kind === "refused" && (
        <div className="card result not-ok">
          <h2>Refused <span className="badge failed">{phase.kind2}</span></h2>
          <p>{phase.message}</p>
          {phase.next.length > 0 && <pre className="next">{phase.next.map(actionLine).join("\n")}</pre>}
        </div>
      )}
    </section>
  );
}
