import { useEffect, useState } from "react";
import { events, lines, tail } from "./api";

// An operation's steps as they run, from its event log (web.md § 1, core.md § 6), and the
// running step's last lines.

interface StepState { id: string; describe: string; outcome?: string }

// The steps are shown as the run reaches them: an operation over several subjects runs once per
// subject, each with its own log, and only its own steps.
export function Progress({ address, steps }: { address: string; steps: { id: string; describe: string }[] }) {
  const describe = new Map(steps.map((s) => [s.id, s.describe]));
  const [states, setStates] = useState<StepState[]>([]);
  const [running, setRunning] = useState<string | null>(null);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [ended, setEnded] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    (async () => {
      for await (const record of lines(await events(address))) {
        if (!live) return;
        if (record.kind === "step-start") {
          setRunning(record.step);
          setStates((s) => [...s, { id: record.step, describe: describe.get(record.step) ?? record.step }]);
        }
        if (record.kind === "step-end") {
          setStates((s) => s.map((x) => (x.id === record.step ? { ...x, outcome: record.outcome } : x)));
          setRunning(null);
        }
        if (record.kind === "operation-end") setEnded(record.outcome);
      }
    })().catch(() => undefined);
    return () => { live = false; };
  }, [address]);

  useEffect(() => {
    if (!running) return;
    let live = true;
    const look = () => tail(address, running).then((l) => live && setLogLines(l)).catch(() => undefined);
    look();
    const timer = setInterval(look, 1000);
    return () => { live = false; clearInterval(timer); };
  }, [address, running]);

  return (
    <div className="progress">
      <div className="progress-head">
        <span className="address">{address}</span>
        <span className={`badge ${ended ?? "running"}`}>{ended ?? "running"}</span>
      </div>
      <ol className="steps">
        {states.map((s) => (
          <li key={s.id} className={s.outcome ?? (s.id === running ? "running" : "pending")}>
            <span className="mark" aria-hidden="true" />
            <span>{s.describe}</span>
          </li>
        ))}
      </ol>
      {running && logLines.length > 0 && <pre className="log">{logLines.join("\n")}</pre>}
    </div>
  );
}
