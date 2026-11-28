// The client (web.md § 9.1): the only code that talks to the server, and the one reader of its
// answers. Every answer comes back as one outcome — ok, refused, defect, token, unreachable,
// unreadable — and is never painted as data. The token is taken once from the address's
// fragment and kept in this tab; it is sent as a Bearer header, never a cookie.

import type {
  DefectAnswer, Document, Documents, Ended, Image, Lines, LogState, OperationInfo, Page, PlanAnswer, RefusalAnswer,
  RunAnswer, Started,
} from "../generated/schemas";
import { Place, viewer } from "./documents";

export type Outcome<T> =
  | { kind: "ok"; value: T }
  | { kind: "refused"; refusal: RefusalAnswer }
  | { kind: "defect"; defect: DefectAnswer }
  | { kind: "token" }
  | { kind: "unreachable" }
  | { kind: "unreadable"; status: number };

/** One line of an apply's answer, as it streams. */
export type ApplyLine =
  | { kind: "started"; started: Started }
  | { kind: "ended"; ended: Ended }
  | { kind: "refused"; refusal: RefusalAnswer }
  | { kind: "defect"; defect: DefectAnswer };

const KEY = "femkit-token";

function takeToken(): string | null {
  const match = window.location.hash.match(/token=([A-Za-z0-9_-]+)/);
  try {
    if (match) {
      sessionStorage.setItem(KEY, match[1]);
      const rest = window.location.hash.slice(1).split("&").filter((p) => !p.startsWith("token=")).join("&");
      history.replaceState(null, "", window.location.pathname + window.location.search + (rest ? "#" + rest : ""));
    }
    return sessionStorage.getItem(KEY);
  } catch {
    return match ? match[1] : null;
  }
}

let token: string | null = takeToken();
const refused = new Set<() => void>();
const given = new Set<() => void>();

export function hasToken(): boolean {
  return !!token;
}

export function setToken(value: string): void {
  token = value;
  try { sessionStorage.setItem(KEY, value); } catch { /* the token lives only in this page */ }
  given.forEach((l) => l());
}

/** Be told when the server refuses the token (401), wherever the page asked — the shell asks for it
 *  again; and when a token is given anew — typed, or in the address's fragment. Returns the end of it. */
export function onToken(lost: () => void, back: () => void): () => void {
  refused.add(lost);
  given.add(back);
  return () => { refused.delete(lost); given.delete(back); };
}

// A new `#token=` in the address, as a move within the page brings it: taken, as at the start.
window.addEventListener("hashchange", () => {
  if (!/token=/.test(window.location.hash)) return;
  const held = token;
  token = takeToken();
  if (token && token !== held) given.forEach((l) => l());
});

/** What every request carries: the token, as a Bearer header. */
export function authorization(): string {
  return `Bearer ${token ?? ""}`;
}

/** The document viewer's address, in a tab of its own, its token handed over as the page's was. */
export function viewerAddress(place: Place = {}): string {
  return viewer(token ?? "", place);
}

async function send(path: string, body?: unknown): Promise<Response | Outcome<never>> {
  try {
    const response = await fetch(path, {
      method: body === undefined ? "GET" : "POST",
      headers: { Authorization: authorization(), ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "omit",
    });
    if (response.status === 401) refused.forEach((l) => l());     // one place for every route the page asks
    return response;
  } catch {
    return { kind: "unreachable" };
  }
}

/** A JSON answer read once, by the one rule every route's answer follows (web.md § 1). */
function read<T>(status: number, data: any): Outcome<T> {
  if (status === 401) return { kind: "token" };
  if (data && typeof data === "object" && "refused" in data) return { kind: "refused", refusal: data };
  if (data && typeof data === "object" && "defect" in data) return { kind: "defect", defect: data };
  if (status >= 400) return { kind: "unreadable", status };
  return { kind: "ok", value: data as T };
}

async function ask<T>(path: string, body?: unknown): Promise<Outcome<T>> {
  const response = await send(path, body);
  if (!(response instanceof Response)) return response;
  if (response.status === 401) return { kind: "token" };
  try {
    return read<T>(response.status, await response.json());
  } catch {
    return { kind: "unreadable", status: response.status };
  }
}

/** Each JSON line of a streamed answer as it arrives; an empty line only keeps it alive. */
async function* jsonLines(response: Response): AsyncGenerator<any> {
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let at: number;
    while ((at = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, at).trim();
      buffer = buffer.slice(at + 1);
      if (line) yield JSON.parse(line);
    }
  }
  if (buffer.trim()) yield JSON.parse(buffer);
}

/** An operation's route (web.md § 1): its command's words, as the server lists them. */
const route = (words: string[]) => "/api/" + words.join("/");

/** One line of an event stream: the log's fold as it changes, or the stream lost before the run ended. */
export type EventLine = { kind: "state"; state: LogState } | { kind: "lost"; why: "unreachable" | "unreadable" };

export const server = {
  page: () => ask<Page>("/api/page"),
  operations: () => ask<OperationInfo[]>("/api/operations"),
  run: (words: string[], request: unknown) => ask<RunAnswer>(route(words), request),
  plan: (words: string[], request: unknown) => ask<PlanAnswer>(route(words) + "/plan", request),

  /** An apply's answer: each run as it starts, then how it ended — or, before any run, a refusal; a
   *  stream that ends before saying how the run ended is lost. */
  async *apply(words: string[], request: unknown, digest: string): AsyncGenerator<ApplyLine | Outcome<never>> {
    const response = await send(route(words) + "/apply", { request, digest });
    if (!(response instanceof Response)) { yield response; return; }
    if (!response.ok || !(response.headers.get("Content-Type") ?? "").includes("ndjson")) {
      let data: any = null;
      try { data = await response.json(); } catch { /* unreadable */ }
      const once = read<Ended>(response.status, data);
      yield once.kind === "ok" ? { kind: "ended", ended: once.value } : once;
      return;
    }
    let ended = false;
    try {
      for await (const line of jsonLines(response)) {
        if ("operation" in line) yield { kind: "started", started: line };
        else if ("refused" in line) { ended = true; yield { kind: "refused", refusal: line }; }
        else if ("defect" in line) { ended = true; yield { kind: "defect", defect: line }; }
        else { ended = true; yield { kind: "ended", ended: line }; }
      }
    } catch { /* the stream broke: said below */ }
    if (!ended) yield { kind: "unreachable" };
  },

  /** An operation's event log, folded, as it changes (core.md § 6); a stream refused, or one that ends
   *  before its run did, said as lost. */
  async *events(address: string): AsyncGenerator<EventLine> {
    const response = await send(`/api/events/${address}`);
    if (!(response instanceof Response)) { yield { kind: "lost", why: "unreachable" }; return; }
    if (!response.ok) { yield { kind: "lost", why: "unreadable" }; return; }
    let last: LogState | null = null;
    try {
      for await (const line of jsonLines(response)) {
        if ("refused" in line) { yield { kind: "lost", why: "unreadable" }; return; }
        last = line as LogState;
        yield { kind: "state", state: last };
      }
    } catch { /* the stream broke: said below */ }
    if (!last || !(last.ended || last.interrupted)) yield { kind: "lost", why: "unreachable" };
  },
  tail: (address: string, step: string) => ask<Lines>(`/api/tail/${address}/${encodeURIComponent(step)}`),
  documents: () => ask<Documents>("/api/docs"),
  document: (path: string) => ask<Document | Image>("/api/docs/" + path.split("/").map(encodeURIComponent).join("/")),
};
