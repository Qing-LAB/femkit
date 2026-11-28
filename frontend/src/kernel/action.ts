// The action machine (web.md § 9.1; framework.md § 3): one state machine for every action, in every
// view — its states and moves the declaration's table (`page.action`), run here as they are written:
// told an event, the machine moves where the table says from the state it is in, and nowhere else. What
// each state shows and the controls it offers are the table's too. What an action does is its own
// `effect`, the server's; its values to fill are the server's fills; a plan's questions (`asks`) become
// values to fill and the plan is made again with them (api.md § 3.1).

import { useCallback, useRef, useState } from "react";
import type {
  Action, ActionMachine, ActionState, DefectAnswer, Fill, OperationInfo, PlanAnswer, RefusalAnswer, Shown,
} from "../generated/schemas";
import { Outcome, server } from "./client";
import { useDeclared } from "./declared";
import { changed } from "./document";
import { started } from "./runs";
import { json, Value, write } from "./toml";

export type Effect = NonNullable<Action["effect"]>;
export type Given = Record<string, Value>;
type Event = ActionMachine["transitions"][number]["on"];

/** What the machine runs: an operation by its route's words, its request, its effect, its values still
 *  to fill — the server's fills — and the words it is known by. */
export interface Act {
  operation: OperationInfo;
  request: Record<string, unknown>;
  fills: Fill[];
  label: string;
}

/** An action of a document as the machine runs it — its operation the one the server lists, its fills
 *  the action's own; none for a shell line or an operation the page is not served. */
export function actOf(action: Action, operations: Map<string, OperationInfo>): Act | null {
  const operation = action.call ? operations.get(action.call.operation) : undefined;
  if (!operation || !action.call) return null;
  return { operation, request: action.call.request, fills: action.fills, label: action.label };
}

/** An operation as a form (web.md § 2.1): the request the context gives, and each other field of its
 *  request a value to fill, as the server builds it. */
export function actFor(operation: OperationInfo, given: Record<string, unknown>): Act {
  return { operation, request: given, fills: operation.fills.filter((f) => !(f.field in given)),
           label: operation.words.join(" ") };
}

/** Whether a value a document holds is an action — a table's cell holds a value or one (web.md
 *  § 7.5): an action is written with every field it has, its line among them. */
export function isAction(v: unknown): v is Action {
  return typeof v === "object" && v !== null && "label" in v && "command" in v && "fills" in v;
}

/** The request once its fills are given: each field's whole value — written as its TOML text where
 *  the request takes it so. */
function requestOf(act: Act, given: Given): Record<string, unknown> {
  const request: Record<string, unknown> = { ...act.request };
  for (const f of act.fills) {
    if (given[f.field] !== undefined) request[f.field] = f.toml ? write(given[f.field]) : json(given[f.field]);
  }
  return request;
}

/** Where the machine stands, and what it holds there. */
export interface Phase {
  state: ActionState;
  fills: Fill[];                       // the values asked now: the action's, or its plan's questions
  answer?: PlanAnswer;
  runs: string[];
  result?: Shown;
  ok?: boolean;
  refusal?: RefusalAnswer;
  defect?: DefectAnswer;
  why?: "token" | "unreachable" | "unreadable";
}

/** The machine for one place in a view: start an act, give its values, apply or discard its plan. */
export function useAction(onDone?: (result: Shown, ok: boolean) => void) {
  const machine = useDeclared().page.action;
  const states = new Map(machine.states.map((s) => [s.key, s]));
  const [phase, setPhase] = useState<Phase>({ state: states.get(machine.start)!, fills: [], runs: [] });
  const at = useRef(phase);
  const act = useRef<Act | null>(null);
  const request = useRef<Record<string, unknown>>({});
  const done = useRef(onDone);
  done.current = onDone;

  /** The move the table gives for ``event`` from where the machine stands, holding ``held``; none
   *  written: it stays. */
  const send = useCallback((event: Event, held: Partial<Phase> = {}) => {
    const move = machine.transitions.find((m) => m.from === at.current.state.key && m.on === event);
    if (!move) return;
    at.current = { ...at.current, ...held, state: states.get(move.to)! };
    setPhase(at.current);
  }, [machine]);

  const settle = useCallback(<T,>(outcome: Outcome<T>, then: (value: T) => void) => {
    if (outcome.kind === "ok") return then(outcome.value);
    if (outcome.kind === "refused") return send("refused", { refusal: outcome.refusal });
    if (outcome.kind === "defect") return send("defect", { defect: outcome.defect });
    send("lost", { why: outcome.kind });
  }, [send]);

  const ended = useCallback((result: Shown, ok: boolean) => {
    send(ok ? "done" : "failed", { result, ok });
    done.current?.(result, ok);
  }, [send]);

  const apply = useCallback(async (answer: PlanAnswer) => {
    const a = act.current!;
    for await (const line of server.apply(a.operation.words, request.current, answer.digest)) {
      if (line.kind === "started") {
        const runs = [...at.current.runs, line.started.operation];
        send("started", { runs });
        started({ address: line.started.operation, label: a.label, steps: answer.plan.steps });
      } else if (line.kind === "ended") {
        ended(line.ended.outcome, line.ended.ok);
        changed();
      } else {
        settle(line, () => undefined);
      }
    }
  }, [send, settle, ended]);

  /** On with the values ``given``: the operation run, or planned — its plan shown, its questions asked,
   *  or, with nothing to do, applied at once. */
  const go = useCallback(async (given: Given) => {
    const a = act.current!;
    request.current = { ...request.current, ...requestOf({ ...a, fills: [...a.fills, ...at.current.fills] }, given) };
    if (a.operation.effect === "reads") {
      send("reads");
      return settle(await server.run(a.operation.words, request.current), (r) => ended(r.result, r.ok));
    }
    send("changes");
    settle(await server.plan(a.operation.words, request.current), (answer) => {
      const asked = answer.plan.asks.map((q) => q.key).filter((k) => !(k in request.current));
      if (asked.length) return send("asks", { answer, fills: a.operation.fills.filter((f) => asked.includes(f.field)) });
      if (answer.plan.steps.length === 0) {
        send("empty", { answer });
        return void apply(answer);
      }
      send("planned", { answer });
    });
  }, [send, settle, ended, apply]);

  /** Start ``next``, with the values its holder gives — the text an editor holds — its other values
   *  to fill asked first, where it has any. */
  const start = useCallback((next: Act, given: Given = {}) => {
    act.current = next;
    request.current = requestOf(next, given);
    const left = next.fills.filter((f) => !(f.field in given));
    at.current = { state: states.get(machine.start)!, fills: left, runs: [] };
    if (left.length) send("fills");
    else void go({});
  }, [go, send, machine]);

  /** The values asked, given. */
  const fill = useCallback((given: Given) => void go(given), [go]);

  /** The plan shown, agreed: applied with its digest. */
  const confirm = useCallback(() => {
    const answer = at.current.answer;
    if (!answer) return;
    send("apply");
    void apply(answer);
  }, [send, apply]);

  /** The values or the plan left, nothing done. */
  const discard = useCallback(() => send("discard"), [send]);

  return { phase, start, fill, confirm, discard };
}

/** The tone of a press that runs an action, by its effect (web.md § 7.2): a read quiet, a change
 *  primary, a removal danger — the one rule, for every press. */
export const TONE: Record<Effect, "quiet" | "primary" | "danger"> = { reads: "quiet", changes: "primary", removes: "danger" };
