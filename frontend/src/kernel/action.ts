// The action machine (web.md § 9.1): one state machine for every action, in every view. A read
// runs; a change is planned at once — planning only reads — then applied with its plan's digest:
// at once when its operation asks no confirmation, else after one press. Whether an operation
// changes things or asks comes from the registry, never from the view.

import { createContext, useCallback, useContext, useRef, useState } from "react";
import type { Action, DefectAnswer, Fill, OperationInfo, RefusalAnswer } from "../generated/schemas";
import { Outcome, server } from "./client";
import { Value, write } from "./toml";

/** The registry's listing, shared by every view (GET /api/operations). */
export const Registry = createContext<Map<string, OperationInfo>>(new Map());

export type Given = Record<string, Value>;

/** Whether a value a document holds is an action — a table's cell holds a value or one (web.md
 *  § 7.5). An action is written with every field it has, its call and its shell line among them. */
export function isAction(v: unknown): v is Action {
  return typeof v === "object" && v !== null && "label" in v && "call" in v && "shell" in v;
}

/** How a fill is named among an action's values: its hole's name, or its field. */
export function fillKey(f: Fill): string {
  return f.hole ? f.hole.replace(/^"?<|>"?$/g, "") : f.field;
}

/** The request an action makes once its fills are given: a hole replaced in its field's text,
 *  a whole value set — written as its TOML text where the request takes it so. */
export function requestOf(action: Action, given: Given): Record<string, unknown> {
  const request: Record<string, unknown> = { ...(action.call?.request ?? {}) };
  for (const f of action.fills ?? []) {
    const v = given[fillKey(f)];
    if (f.hole) request[f.field] = String(request[f.field]).split(f.hole).join(typeof v === "string" ? v : write(v));
    else request[f.field] = f.toml ? write(v) : v;
  }
  return request;
}

export type Phase =
  | { is: "idle" }
  | { is: "running" }
  | { is: "planning" }
  | { is: "planned"; plan: any; digest: string; request: Record<string, unknown> }
  | { is: "applying"; plan: any; runs: string[] }
  | { is: "done"; ok: boolean; answer: any; plan?: any }
  | { is: "refused"; refusal: RefusalAnswer }
  | { is: "defect"; defect: DefectAnswer }
  | { is: "lost"; why: "token" | "unreachable" | "unreadable" };

export interface Handlers {
  done?: (answer: any, ok: boolean) => void;
  started?: (address: string, plan: any) => void;
  lostToken?: () => void;
}

/** The machine for one place in a view: perform an action, then apply or discard its plan. */
export function useAction(handlers: Handlers = {}) {
  const registry = useContext(Registry);
  const [phase, setPhase] = useState<Phase>({ is: "idle" });
  const latest = useRef(handlers);
  latest.current = handlers;

  const settle = useCallback(<T,>(outcome: Outcome<T>, then: (value: T) => void) => {
    if (outcome.kind === "ok") return then(outcome.value);
    if (outcome.kind === "refused") return setPhase({ is: "refused", refusal: outcome.refusal });
    if (outcome.kind === "defect") return setPhase({ is: "defect", defect: outcome.defect });
    if (outcome.kind === "token") latest.current.lostToken?.();
    setPhase({ is: "lost", why: outcome.kind === "unreadable" ? "unreadable" : outcome.kind });
  }, []);

  const apply = useCallback(async (operation: string, request: Record<string, unknown>, plan: any, digest: string) => {
    const runs: string[] = [];
    setPhase({ is: "applying", plan, runs });
    for await (const line of server.apply(operation, request, digest)) {
      if (line.kind === "started") {
        runs.push(line.started.operation);
        setPhase({ is: "applying", plan, runs: [...runs] });
        latest.current.started?.(line.started.operation, plan);
      } else if (line.kind === "ended") {
        setPhase({ is: "done", ok: line.ended.ok, answer: line.ended.outcome, plan });
        latest.current.done?.(line.ended.outcome, line.ended.ok);
      } else {
        settle(line as Outcome<never>, () => undefined);
      }
    }
  }, [settle]);

  const perform = useCallback(async (action: Action, given: Given = {}) => {
    if (!action.call) return;
    const { operation } = action.call;
    const op = registry.get(operation);
    const request = requestOf(action, given);
    if (!op?.changes) {
      setPhase({ is: "running" });
      return settle(await server.run(operation, request), (a) => {
        setPhase({ is: "done", ok: a.ok, answer: a.result });
        latest.current.done?.(a.result, a.ok);
      });
    }
    setPhase({ is: "planning" });
    settle(await server.plan(operation, request), (a) => {
      if (a.plan.steps.length === 0) return void apply(operation, request, a.plan, a.digest);
      setPhase({ is: "planned", plan: a.plan, digest: a.digest, request });
    });
  }, [registry, settle, apply]);

  const confirm = useCallback(() => {
    if (phase.is !== "planned") return;
    void apply(phase.plan.operation, phase.request, phase.plan, phase.digest);
  }, [phase, apply]);

  const reset = useCallback(() => setPhase({ is: "idle" }), []);

  return { phase, perform, confirm, reset };
}
