import { useEffect, useState } from "react";
import { server } from "../kernel/client";
import { Badge } from "./Badge";
import "./Progress.css";

// A run's steps as they go, from its event log, and the running step's last lines (web.md § 9.2).

interface StepState { id: string; describe: string; outcome?: string }

export function Progress({ address, steps }: { address: string; steps: { id: string; describe: string }[] }) {
  const [states, setStates] = useState<StepState[]>([]);
  const [running, setRunning] = useState<string | null>(null);
  const [lines, setLines] = useState<string[]>([]);
  const [ended, setEnded] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    const describe = new Map(steps.map((s) => [s.id, s.describe]));
    (async () => {
      for await (const r of server.events(address)) {
        if (!live) return;
        if (r.kind === "step-start") {
          setRunning(String(r.step));
          setStates((s) => [...s, { id: String(r.step), describe: describe.get(String(r.step)) ?? String(r.step) }]);
        } else if (r.kind === "step-end") {
          setStates((s) => s.map((x) => (x.id === r.step ? { ...x, outcome: String(r.outcome) } : x)));
          setRunning(null);
        } else if (r.kind === "operation-end") setEnded(String(r.outcome));
      }
    })();
    return () => { live = false; };
  }, [address, steps]);
  useEffect(() => {
    if (!running) return;
    let live = true;
    const look = () => server.tail(address, running).then((o) => { if (live && o.kind === "ok") setLines(o.value.lines ?? []); });
    look();
    const timer = setInterval(look, 1000);
    return () => { live = false; clearInterval(timer); };
  }, [address, running]);
  return (
    <div className="progress">
      <div className="progress__head"><span className="progress__what">{steps.length} step{steps.length === 1 ? "" : "s"}</span>
        <Badge meaning={ended === "done" ? "ok" : ended ? "bad" : "info"}>{ended ?? "running"}</Badge></div>
      <ol className="progress__steps">
        {states.map((s) => <li key={s.id} className={`progress__step progress__step--${s.outcome ?? (s.id === running ? "running" : "waiting")}`}>{s.describe}</li>)}
      </ol>
      {running && lines.length > 0 && <pre className="progress__log">{lines.join("\n")}</pre>}
    </div>
  );
}
