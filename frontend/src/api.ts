// Every request the first page makes (web.md § 1, § 5), with the token the kernel's client keeps:
// taken from the address's fragment, kept in this tab's session storage, sent as Bearer; never a
// cookie.

import type { Action, OperationInfo as Listed } from "./generated/schemas";
import { authorization } from "./kernel/client";

export { hasToken, setToken, viewerAddress } from "./kernel/client";

export class NeedToken extends Error {}

export class Refused extends Error {
  constructor(public kind: string, message: string, public next: Action[]) {
    super(message);
  }
}

/** An operation as the registry lists it, its schemas read as the forms read them. */
export type OperationInfo = Listed & { request: JsonSchema; result: JsonSchema };

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

async function send(path: string, body?: unknown): Promise<Response> {
  const headers: Record<string, string> = { Authorization: authorization() };
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
    throw new Refused(String(data.refused), String(data.message), (data.next as Action[]) ?? []);
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

export interface DocText { path: string; text: string; headings: { level: number; text: string; anchor: string }[] }

export async function docsList(): Promise<string[]> {
  return (await json(await send("/api/docs"))).files as string[];
}

export async function docText(path: string): Promise<DocText> {
  const response = await send("/api/docs/" + path.split("/").map(encodeURIComponent).join("/"));
  if (response.status === 404) throw new Refused("missing", `${path} is not one of the documents`, []);
  return json(response);
}

export async function docImage(path: string): Promise<string | null> {
  const response = await send("/api/docs/" + path.split("/").map(encodeURIComponent).join("/"));
  if (!response.ok) return null;
  const data = await response.json();
  return data.type && data.data ? `data:${data.type};base64,${data.data}` : null;
}
