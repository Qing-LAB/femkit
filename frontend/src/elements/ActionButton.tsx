import { useContext, useEffect, useState } from "react";
import type { Action } from "../generated/schemas";
import { fillKey, Given, useAction } from "../kernel/action";
import { NamesOf } from "../kernel/names";
import { notify } from "../kernel/notify";
import type { Value } from "../kernel/toml";
import { Button, type Tone } from "./Button";
import { Dialog } from "./Dialog";
import { Field } from "./Field";
import { Plan } from "./Plan";
import { Progress } from "./Progress";

// Any action (web.md § 9.2): the values it still needs asked, then the action machine — its
// plan shown where its operation asks, its progress while it applies, its refusal with the next
// steps the refusal offers. What applied is said once, in the notification stack.

/** An action carried through: the values it still needs asked, its plan where its operation
 *  asks, its progress, its refusal — opened by a press, a wire, a drop. ``onClose`` ends it. */
export function ActionFlow({ action, given = {}, onDone, onClose }: {
  action: Action; given?: Given; onDone?: (answer: any) => void; onClose: () => void;
}) {
  const namesOf = useContext(NamesOf);
  const open = (action.fills ?? []).filter((f) => !(fillKey(f) in given));
  const [asking, setAsking] = useState(open.length > 0);
  const [values, setValues] = useState<Given>({});
  const { phase, perform, confirm } = useAction({
    done: (answer, ok) => {
      if (!ok) return;
      notify("ok", action.label);
      onDone?.(answer);
      onClose();
    },
  });
  useEffect(() => { if (!open.length) void perform(action, given); }, []);   // nothing to ask: on at once
  const showing = asking || ["planned", "applying", "refused", "defect"].includes(phase.is) || (phase.is === "done" && !phase.ok);
  if (!showing) return null;
  return (
    <Dialog title={action.label} onClose={onClose} wide={phase.is === "applying"}
            foot={asking ? (
              <>
                <Button tone="ghost" onClick={onClose}>Cancel</Button>
                <Button tone="primary" disabled={open.some((f) => values[fillKey(f)] === undefined)}
                        onClick={() => { setAsking(false); void perform(action, { ...given, ...values }); }}>Continue</Button>
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
          {(phase.refusal.next ?? []).filter((a) => a.call).map((a, i) => <ActionButton key={i} action={a} small />)}
        </div>
      )}
      {phase.is === "defect" && <p>{phase.defect.message}{phase.defect.log ? ` — ${phase.defect.log}` : ""}</p>}
      {phase.is === "done" && !phase.ok && <Plan plan={{ steps: [], issues: phase.answer?.issues ?? [] }} />}
    </Dialog>
  );
}

/** Any action as a press (web.md § 9.2). */
export function ActionButton({ action, tone = "quiet", icon, small, given = {}, label, onDone, disabled }: {
  action: Action; tone?: Tone; icon?: string; small?: boolean; given?: Given; label?: string;
  onDone?: (answer: any) => void; disabled?: boolean;
}) {
  const [running, setRunning] = useState(0);
  return (
    <>
      <Button tone={tone} icon={icon} small={small} disabled={disabled} title={action.help?.sentence ?? action.command}
              onClick={() => setRunning((n) => n + 1)}>{label ?? action.label}</Button>
      {running > 0 && <ActionFlow key={running} action={action} given={given} onDone={onDone} onClose={() => setRunning(0)} />}
    </>
  );
}
