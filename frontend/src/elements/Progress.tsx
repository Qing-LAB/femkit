import { useEffect, useState } from "react";
import type { LogState, Step } from "../generated/schemas";
import bundle from "../generated/bundle.json";
import { server } from "../kernel/client";
import { useSaying } from "../kernel/declared";
import { measure } from "../kernel/tokens";
import { Badge } from "./Badge";
import { Sentence } from "./Sentence";
import "./Progress.css";

// A run's steps as they go (web.md § 9.2): the operation's event log as the server folds it
// (`LogState`, core.md § 6) — each step with its word, marked by the colour the declaration binds it
// to — and the running step's last lines, read as often as the theme says. A stream refused, or one
// that ends before its run did, is said.

export function Progress({ address, steps, label }: { address: string; steps: Step[]; label?: string }) {
  const [state, setState] = useState<LogState | null>(null);
  const [lost, setLost] = useState<"unreachable" | "unreadable" | null>(null);
  const [lines, setLines] = useState<string[]>([]);
  const runningWord = useSaying("running");
  useEffect(() => {
    let live = true;
    (async () => {
      for await (const line of server.events(address)) {
        if (!live) return;
        if (line.kind === "state") setState(line.state); else setLost(line.why);
      }
    })();
    return () => { live = false; };
  }, [address]);
  const running = state?.running ?? null;
  useEffect(() => {
    if (!running) return;
    let live = true;
    const look = () => server.tail(address, running).then((o) => { if (live && o.kind === "ok") setLines(o.value.lines); });
    void look();
    const timer = setInterval(look, measure("motion-poll"));
    return () => { live = false; clearInterval(timer); };
  }, [address, running]);
  const describe = new Map(steps.map((s) => [s.id, s.describe]));
  return (
    <div className="progress">
      <div className="progress__head">
        <span className="progress__what">{label ?? address}</span>
        <span data-outcome={state?.outcome ?? undefined}><Badge toned={!!state?.outcome}>{state?.outcome ?? runningWord}</Badge></span>
      </div>
      <ol className="progress__steps">
        {(state?.steps ?? []).map((s) => (
          <li key={s.id} className="progress__step" data-outcome={s.outcome}>{describe.get(s.id) ?? s.id}</li>
        ))}
      </ol>
      {running && lines.length > 0 && <pre className="progress__log">{lines.join("\n")}</pre>}
      {lost && <p className="progress__lost"><Sentence text={bundle.gate.says[lost]} /></p>}
    </div>
  );
}
