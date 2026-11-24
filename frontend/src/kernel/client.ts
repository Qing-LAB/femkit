// The client (web.md § 9.1): the only code that talks to the server, and the one reader of its
// answers. Every answer comes back as one outcome — ok, refused, defect, token, unreachable,
// unreadable — and is never painted as data. The token is taken once from the address's
// fragment and kept in this tab; it is sent as a Bearer header, never a cookie.

import type {
  DefectAnswer, Document, Documents, Ended, Image, Lines, OperationInfo, Page, PlanAnswer, RefusalAnswer, RunAnswer,
  Started,
} from "../generated/schemas";

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

export function hasToken(): boolean {
  return !!token;
}

export function setToken(value: string): void {
  token = value;
  try { sessionStorage.setItem(KEY, value); } catch { /* the token lives only in this page */ }
}

/** What every request carries: the token, as a Bearer header. */
export function authorization(): string {
  return `Bearer ${token ?? ""}`;
}

/** The document viewer's address, in a tab of its own, its token handed over as the page's was. */
export function viewerAddress(document?: string, section?: string | null): string {
  const parts = [`token=${token ?? ""}`, document ? `doc=${encodeURIComponent(document)}` : "",
                 section ? `at=${encodeURIComponent(section)}` : ""];
  return "/docs#" + parts.filter(Boolean).join("&");
}

async function send(path: string, body?: unknown): Promise<Response | Outcome<never>> {
  try {
    return await fetch(path, {
      method: body === undefined ? "GET" : "POST",
      headers: { Authorization: authorization(), ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "omit",
    });
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

const route = (operation: string) => "/api/" + operation.replace(/\./g, "/");

export const server = {
  page: () => ask<Page>("/api/page"),
  operations: () => ask<OperationInfo[]>("/api/operations"),
  run: (operation: string, request: unknown) => ask<RunAnswer>(route(operation), request),
  plan: (operation: string, request: unknown) => ask<PlanAnswer>(route(operation) + "/plan", request),

  /** An apply's answer: each run as it starts, then how it ended — or, before any run, a refusal. */
  async *apply(operation: string, request: unknown, digest: string): AsyncGenerator<ApplyLine | Outcome<never>> {
    const response = await send(route(operation) + "/apply", { request, digest });
    if (!(response instanceof Response)) { yield response; return; }
    if (!response.ok || !(response.headers.get("Content-Type") ?? "").includes("ndjson")) {
      let data: any = null;
      try { data = await response.json(); } catch { /* unreadable */ }
      const once = read<Ended>(response.status, data);
      yield once.kind === "ok" ? { kind: "ended", ended: once.value } : once;
      return;
    }
    for await (const line of jsonLines(response)) {
      if ("operation" in line) yield { kind: "started", started: line };
      else if ("refused" in line) yield { kind: "refused", refusal: line };
      else if ("defect" in line) yield { kind: "defect", defect: line };
      else yield { kind: "ended", ended: line };
    }
  },

  /** An operation's event log as it grows (core.md § 6). */
  async *events(address: string): AsyncGenerator<Record<string, unknown>> {
    const response = await send(`/api/events/${address}`);
    if (!(response instanceof Response) || !response.ok) return;
    yield* jsonLines(response);
  },
  tail: (address: string, step: string) => ask<Lines>(`/api/tail/${address}/${encodeURIComponent(step)}`),
  documents: () => ask<Documents>("/api/docs"),
  document: (path: string) => ask<Document | Image>("/api/docs/" + path.split("/").map(encodeURIComponent).join("/")),
};
