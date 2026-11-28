import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Action, DefectAnswer, RefusalAnswer, Shown } from "../generated/schemas";
import bundle from "../generated/bundle.json";
import { Act, actOf, Given, Phase, TONE, useAction } from "../kernel/action";
import { useControl, useDeclared, useSaying } from "../kernel/declared";
import { close as closeFlow, open as openFlow, useOpened } from "../kernel/flows";
import { mark } from "../kernel/marks";
import { notify } from "../kernel/notify";
import type { Value } from "../kernel/toml";
import { Button } from "./Button";
import { Card } from "./Card";
import { Dialog } from "./Dialog";
import { Field } from "./Field";
import { Issues } from "./Issue";
import { Plan } from "./Plan";
import { Progress } from "./Progress";
import { Report } from "./Report";
import { Sentence } from "./Sentence";
import "./ActionButton.css";

// Any action (web.md §§ 7.2, 9.1, 9.2): one renderer of an `Action`, and one flow every action runs
// through, in a dialog or in a view. Its words, its line, its effect and its values to fill are the
// server's: a read is a quiet press, a change a primary one, a removal a danger one, at the press that
// starts it and at the one that applies it — each banded by its operation's group's accent. What the
// flow shows and the controls it offers are the action machine's states', as the declaration writes
// them; an outcome stays, its report and next steps, until the person closes it. A shell line, or a
// step for another machine (`on`), is no press: it is its line, to copy.

export function RefusalShown({ refusal }: { refusal: RefusalAnswer }) {
  const heading = useSaying("refused");
  return (
    <section className="action__refusal">
      <h4 className="action__heading">{heading}</h4>
      <Issues issues={refusal.issues} />
      <p className="action__message"><Sentence text={refusal.message} /></p>
      {refusal.next.length > 0 && <Actions actions={refusal.next} />}
    </section>
  );
}

export function DefectShown({ defect }: { defect: DefectAnswer }) {
  const heading = useSaying("defect");
  return (
    <section className="action__refusal">
      <h4 className="action__heading">{heading}</h4>
      <p className="action__message">{defect.message}</p>
      {defect.log && <code className="action__line">{defect.log}</code>}
    </section>
  );
}

/** What the machine's state shows (web.md § 9.1), from what it holds. */
function Shows({ phase, given, setGiven, act }: {
  phase: Phase; given: Given; setGiven: (f: (g: Given) => Given) => void; act: Act;
}) {
  const says = useDeclared().page.says;
  switch (phase.state.shows) {
    case "fills":
      return <>{phase.fills.map((f) => (
        <Field key={f.field} fill={f} value={given[f.field]} suggest={act.operation.choices[f.field]}
               onChange={(v) => setGiven((g) => {
                 const n = { ...g };
                 if (v === undefined) delete n[f.field]; else n[f.field] = v as Value;
                 return n;
               })} />
      ))}</>;
    case "busy":
      return <p className="action__busy">{says.loading}</p>;
    case "plan":
      return phase.answer ? <Plan answer={phase.answer} /> : null;
    case "progress":
      return <>{phase.runs.map((r) => <Progress key={r} address={r} steps={phase.answer?.plan.steps ?? []} />)}</>;
    case "outcome":
      return phase.result ? <Outcome result={phase.result} ok={!!phase.ok} /> : null;
    case "refusal":
      return phase.refusal ? <RefusalShown refusal={phase.refusal} /> : null;
    case "defect":
      return phase.defect ? <DefectShown defect={phase.defect} /> : null;
    case "lost":
      return phase.why ? <p className="action__lost"><Sentence text={bundle.gate.says[phase.why === "token" ? "token" : phase.why]} /></p> : null;
    default:
      return null;
  }
}

function Outcome({ result, ok }: { result: Shown; ok: boolean }) {
  const says = useDeclared().page.says;
  return (
    <>
      <h4 className="action__heading">{says.outcome}</h4>
      <Report report={result.report} issues={result.issues} />
      {result.log && !ok && <code className="action__line">{result.log}</code>}
    </>
  );
}

/** One action carried through the machine, from its press: in a dialog (``inline`` false) closed by
 *  the person — or docked beside the workspaces, so its plan's marks are seen on every diagram — or
 *  in a view, its form — an operation of the Operations workspace. ``values`` are those its holder
 *  gives — an editor's text — never asked; ``done`` is told how it ended. While its plan is shown,
 *  what its findings are about is marked on the diagrams (web.md § 2.4). */
export function Flow({ act, onClose, inline, docked, head, values, done }: {
  act: Act; onClose?: () => void; inline?: boolean; docked?: boolean; head?: ReactNode; values?: Given;
  done?: (ok: boolean) => void;
}) {
  const { page } = useDeclared();
  const controls = page.controls;
  const [given, setGiven] = useState<Given>({});
  // A run goes on to its end whether or not the page still reads (web.md § 1): one whose flow was
  // closed before it ended says how it ended in the notification stack.
  const shut = useRef(false);
  useEffect(() => () => { shut.current = true; }, []);
  const { phase, start, fill, confirm, discard } = useAction((result, ok) => {
    done?.(ok);
    if (shut.current) notify(ok ? "ok" : "bad", act.label, ok ? page.says.applied : result.status ?? undefined);
  });
  const begun = useRef(false);
  useEffect(() => { if (!inline && !begun.current) { begun.current = true; start(act, values); } }, [act, start, inline, values]);
  useEffect(() => (phase.state.shows === "plan" && phase.answer ? mark(phase.answer.plan.issues) : undefined),
            [phase.state.shows, phase.answer]);
  // In a view the form is the act's values, always there; the plan's questions, where it asks any, are
  // the values it asks then. In a dialog, what the machine asks.
  const asked = !inline || phase.state.shows === "fills" ? phase.fills : act.fills;
  const missing = asked.some((f) => f.required && given[f.field] === undefined);
  const tone = TONE[act.operation.effect as keyof typeof TONE];
  const close = () => { discard(); onClose?.(); };
  const press: Record<string, () => ReactNode> = {
    cancel: () => <Button key="cancel" title={controls.cancel.help} onClick={close}>{controls.cancel.label}</Button>,
    continue: () => <Button key="continue" tone="primary" icon={controls.continue.icon} title={controls.continue.help}
                            disabled={missing} onClick={() => fill(given)}>{controls.continue.label}</Button>,
    discard: () => <Button key="discard" icon={controls.discard.icon} title={controls.discard.help}
                           onClick={inline ? discard : close}>{controls.discard.label}</Button>,
    apply: () => <Button key="apply" tone={tone} icon={controls.apply.icon} title={controls.apply.help}
                         onClick={confirm}>{controls.apply.label}</Button>,
    close: () => (inline || docked ? null : <Button key="close" onClick={close}>{controls.close.label}</Button>),
  };
  const offers = phase.state.offers.map((o) => press[o]?.()).filter(Boolean);
  const body = <Shows phase={phase} given={given} setGiven={setGiven} act={act} />;
  if (docked) {
    return (
      <aside className="action__dock" data-group={act.operation.group} aria-label={act.label}>
        <header className="action__dock-head">
          <h3 className="action__dock-title">{act.label}</h3>
          <Button bare small icon={controls.close.icon} aria-label={controls.close.label} title={controls.close.help}
                  onClick={close} />
        </header>
        <div className="action__dock-body">{body}</div>
        {offers.length > 0 && <footer className="action__dock-foot">{offers}</footer>}
      </aside>
    );
  }
  if (!inline) {
    return <Dialog title={act.label} onClose={close} wide={phase.state.shows !== "fills"} foot={offers.length ? <>{offers}</> : undefined}>{body}</Dialog>;
  }
  // In a view, the form's press starts the machine with its values.
  const run = act.operation.effect === "reads" ? controls.run : controls.plan;
  const idle = phase.state.key === page.action.start;
  return (
    <div className="action__flow">
      {head}
      <Card foot={<>{idle || phase.state.shows === "outcome" || phase.state.shows === "refusal"
        ? <Button tone={tone} icon={run.icon} title={run.help} disabled={missing}
                  onClick={() => { start(act); if (act.fills.length) fill(given); }}>{run.label}</Button>
        : offers}</>}>
        {asked.length === 0 ? <p className="action__busy">{page.says["no-request"]}</p>
          : asked.map((f) => (
            <Field key={f.field} fill={f} value={given[f.field]} suggest={act.operation.choices[f.field]}
                   onChange={(v) => setGiven((g) => {
                     const n = { ...g };
                     if (v === undefined) delete n[f.field]; else n[f.field] = v as Value;
                     return n;
                   })} />
          ))}
      </Card>
      {phase.state.shows !== "fills" && phase.state.shows !== "nothing" && body}
    </div>
  );
}

/** A line to type, for what is no operation here: a shell's, or a step for another machine. */
function Line({ action }: { action: Action }) {
  const copy = useControl("copy");
  return (
    <span className="action__shell" title={action.help?.sentence ?? action.note ?? undefined}>
      <code className="action__line">{action.command}</code>
      <Button bare small icon={copy.icon} aria-label={copy.label} title={copy.help}
              onClick={() => void navigator.clipboard?.writeText(action.command)} />
    </span>
  );
}

export function ActionButton({ action, words = "label" }: { action: Action; words?: "label" | "command" }) {
  const { operations } = useDeclared();
  const act = actOf(action, operations);
  if (!act || action.on) return <Line action={action} />;
  return (
    <span className="action" data-group={act.operation.group}>
      <Button tone={TONE[act.operation.effect as keyof typeof TONE]} small title={action.help?.sentence ?? action.command}
              onClick={() => openFlow(act)}>{words === "command" ? action.command : action.label}</Button>
    </span>
  );
}

/** Every action open, in a dialog or docked, each until the person closes it: drawn once, by the shell. */
export function Flows() {
  return <>{useOpened().map((o) => <Flow key={o.id} act={o.act} values={o.values} docked={o.docked} done={o.done}
                                         onClose={() => closeFlow(o.id)} />)}</>;
}

/** Actions of one label — the same step for several subjects — as one press with their count, opening
 *  a menu of each one by its line, and the machine it is for where it is another's. */
function Several({ actions }: { actions: Action[] }) {
  const { operations } = useDeclared();
  const [open, setOpen] = useState(false);
  const [end, setEnd] = useState(false);      // the menu opened toward the start, where the press stands near the end
  const box = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const at = box.current?.getBoundingClientRect();
    setEnd(!!at && at.left > window.innerWidth / 2);
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", key); };
  }, [open]);
  const first = actOf(actions[0], operations);
  return (
    <span className="action action--several" ref={box} data-group={first?.operation.group}>
      <Button tone={first ? TONE[first.operation.effect as keyof typeof TONE] : "quiet"} small aria-expanded={open}
              aria-haspopup="menu" title={actions[0].help?.sentence ?? undefined} onClick={() => setOpen((o) => !o)}>
        {actions[0].label}<span className="action__count">{actions.length}</span>
      </Button>
      {open && (
        <span className={`action__menu ${end ? "action__menu--end" : ""}`} role="menu">
          {actions.map((a, i) => (
            <span key={i} className="action__item" role="menuitem">
              <ActionButton action={a} words="command" />
              {a.on && <span className="action__on">{a.on}</span>}
            </span>
          ))}
        </span>
      )}
    </span>
  );
}

/** Actions side by side, each banded by its group's accent; those of one label as one press with
 *  their count (web.md § 7.7), in the order the first of each stands. */
export function Actions({ actions }: { actions: Action[] }) {
  const byLabel = new Map<string, Action[]>();
  for (const a of actions) byLabel.set(a.label, [...(byLabel.get(a.label) ?? []), a]);
  return (
    <div className="action__row">
      {[...byLabel.values()].map((same, i) => (same.length === 1 ? <ActionButton key={i} action={same[0]} />
                                                                  : <Several key={i} actions={same} />))}
    </div>
  );
}
