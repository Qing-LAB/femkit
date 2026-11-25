import { useContext, useEffect, useState } from "react";
import type { Action } from "../generated/schemas";
import { fillKey, Given, Registry, useAction } from "../kernel/action";
import { NamesOf } from "../kernel/names";
import { notify } from "../kernel/notify";
import type { Value } from "../kernel/toml";
import { Button, type Tone } from "./Button";
import { Dialog } from "./Dialog";
import { Field } from "./Field";
import { Plan } from "./Plan";
import { Progress } from "./Progress";
import { Report } from "./Report";
import "./ActionButton.css";

// Any action (web.md § 9.2): the values it still needs asked, then the action machine — a
// change's plan shown first, its progress while it applies, its refusal with the next
// steps the refusal offers. What applied is said once, in the notification stack; what a read
// answered, when no view takes the answer, is shown by its report. A shell line is no operation:
// it is shown as the text a person copies. The page writes no command line of its own.

/** An action carried through: the values it still needs asked, a change's plan, its progress,
 *  its refusal — opened by a press. ``onClose`` ends it. */
function ActionFlow({ action, onDone, onClose }: {
  action: Action; onDone?: (answer: any) => void; onClose: () => void;
}) {
  const namesOf = useContext(NamesOf);
  const registry = useContext(Registry);
  const shows = !onDone && !registry.get(action.call?.operation ?? "")?.changes;   // a read nobody takes: its answer
  const open = action.fills ?? [];
  const [asking, setAsking] = useState(open.length > 0);
  const [values, setValues] = useState<Given>({});
  const { phase, perform, confirm } = useAction({
    done: (answer, ok) => {
      if (!ok || shows) return;
      notify("ok", action.label);
      onDone?.(answer);
      onClose();
    },
  });
  useEffect(() => { if (!open.length) void perform(action); }, []);   // nothing to ask: on at once
  const answered = phase.is === "done" && (!phase.ok || shows);
  const showing = asking || ["planned", "applying", "refused", "defect"].includes(phase.is) || answered;
  if (!showing) return null;
  return (
    <Dialog title={action.label} onClose={onClose} wide={phase.is === "applying" || answered}
            foot={asking ? (
              <>
                <Button tone="ghost" onClick={onClose}>Cancel</Button>
                <Button tone="primary" disabled={open.some((f) => values[fillKey(f)] === undefined)}
                        onClick={() => { setAsking(false); void perform(action, values); }}>Continue</Button>
              </>
            ) : phase.is === "planned" ? (
              <>
                <Button tone="ghost" onClick={onClose}>Discard</Button>
                <Button tone="primary" icon="check" onClick={confirm}>Apply</Button>
              </>
            ) : <Button onClick={onClose}>Close</Button>}>
      {asking && open.map((f) => (
        <Field key={fillKey(f)} name={fillKey(f)} label={f.label} schema={f.json_schema ?? {}} help={f.help}
               names={f.accepts?.length ? namesOf(f.accepts) : undefined} value={values[fillKey(f)]}
               onChange={(v) => setValues((vs) => {
                 const n = { ...vs };
                 if (v === undefined) delete n[fillKey(f)]; else n[fillKey(f)] = v as Value;
                 return n;
               })} />
      ))}
      {phase.is === "planned" && <Plan plan={phase.plan} />}
      {phase.is === "applying" && phase.runs.map((r) => <Progress key={r} address={r} steps={phase.plan.steps} />)}
      {phase.is === "refused" && (
        <div className="action__refusal">
          <p>{phase.refusal.message}</p>
          {(phase.refusal.next ?? []).map((a, i) => <ActionButton key={i} action={a} small />)}
        </div>
      )}
      {phase.is === "defect" && <p>{phase.defect.message}{phase.defect.log ? ` — ${phase.defect.log}` : ""}</p>}
      {phase.is === "done" && answered && <Report result={phase.answer ?? {}} />}
    </Dialog>
  );
}

/** Any action (web.md § 9.2): an operation as a press, a shell line as the text a person copies. */
export function ActionButton({ action, tone = "quiet", icon, small, label, onDone, disabled }: {
  action: Action; tone?: Tone; icon?: string; small?: boolean; label?: string;
  onDone?: (answer: any) => void; disabled?: boolean;
}) {
  const [running, setRunning] = useState(0);
  const about = action.help?.sentence ?? action.note ?? undefined;
  if (!action.call) return <code className="action__shell" title={about}>{action.shell}</code>;
  return (
    <>
      <Button tone={tone} icon={icon} small={small} disabled={disabled} title={about}
              onClick={() => setRunning((n) => n + 1)}>{label ?? action.label}</Button>
      {running > 0 && <ActionFlow key={running} action={action} onDone={onDone} onClose={() => setRunning(0)} />}
    </>
  );
}
