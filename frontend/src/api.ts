// Every request the page makes (api.md § 5.1, § 5.5): the token from the address's fragment,
// kept in this tab's session storage, sent as Bearer; never a cookie.

const KEY = "femkit-token";

export class NeedToken extends Error {}

export class Refused extends Error {
  constructor(public kind: string, message: string, public next: string[]) {
    super(message);
  }
}

export interface OperationInfo {
  name: string;
  description: string;
  changes: boolean;
  request: JsonSchema;
  result: JsonSchema;
}

export interface JsonSchema {
  type?: string | string[];
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  const?: unknown;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  anyOf?: JsonSchema[];
  allOf?: JsonSchema[];
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  minimum?: number;
  maximum?: number;
  additionalProperties?: boolean | JsonSchema;
}

/** The token: taken once from the address's fragment, then the address is cleaned. */
export function takeToken(): string | null {
  const match = window.location.hash.match(/token=([A-Za-z0-9_-]+)/);
  try {
    if (match) {
      sessionStorage.setItem(KEY, match[1]);
      history.replaceState(null, "", window.location.pathname + window.location.search);
    }
    return sessionStorage.getItem(KEY);
  } catch {
    return match ? match[1] : null;
  }
}

export function setToken(token: string): void {
  try {
    sessionStorage.setItem(KEY, token);
  } catch {
    /* storage refused: the token lives only in this page */
  }
  current = token;
}

let current: string | null = takeToken();

export function hasToken(): boolean {
  return current !== null && current !== "";
}

async function send(path: string, body?: unknown): Promise<Response> {
  const headers: Record<string, string> = { Authorization: `Bearer ${current ?? ""}` };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "omit",
  });
  if (response.status === 401) throw new NeedToken();
  return response;
}

async function json(response: Response): Promise<any> {
  const data = await response.json();
  if (data && typeof data === "object" && "refused" in data) {
    throw new Refused(String(data.refused), String(data.message), (data.next as string[]) ?? []);
  }
  if (data && typeof data === "object" && "defect" in data) {
    throw new Refused("defect", `${data.message}${data.log ? ` (log: ${data.log})` : ""}`, []);
  }
  return data;
}

export async function operations(): Promise<OperationInfo[]> {
  return json(await send("/api/operations"));
}

export function route(name: string): string {
  return "/api/" + name.replace(/\./g, "/");
}

export async function runOperation(name: string, request: unknown): Promise<{ ok: boolean; result: any }> {
  return json(await send(route(name), request));
}

export async function planOperation(name: string, request: unknown): Promise<{ plan: any; digest: string; text: string }> {
  return json(await send(route(name) + "/plan", request));
}

/** Each JSON line of a streamed answer, as it arrives; an empty line keeps the stream alive. */
export async function* lines(response: Response): AsyncGenerator<any> {
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

export async function apply(name: string, request: unknown, digest: string): Promise<Response> {
  const response = await send(route(name) + "/apply", { request, digest });
  if (!response.ok) await json(response); // a refusal before the run starts
  return response;
}

export async function events(address: string): Promise<Response> {
  return send(`/api/events/${address}`);
}

export async function tail(address: string, step: string): Promise<string[]> {
  const data = await json(await send(`/api/tail/${address}/${encodeURIComponent(step)}`));
  return data.lines as string[];
}
