// Markdown as the repository's documents are written (web.md § 2): GitHub's tables and code,
// math between dollar signs, Mermaid diagrams. Raw HTML is shown as text (`html: false`); every
// link is decided here, against the list of documents.
import MarkdownIt from "markdown-it";
import { fragment } from "../kernel/documents";
import type StateBlock from "markdown-it/lib/rules_block/state_block.mjs";
import type StateInline from "markdown-it/lib/rules_inline/state_inline.mjs";

export interface RenderEnv {
  path: string;                       // the document rendered, from the repository's root
  anchors: string[];                  // its headings' anchors, in order, from the server
  documents: Set<string>;             // every document the viewer shows
  heading: number;
  spans: boolean[];                   // for each open link: rendered as a path, not followed
}

/** A path relative to the document's folder, resolved; null when it leaves the repository. */
export function resolvePath(from: string, target: string): string | null {
  const parts = from.split("/").slice(0, -1);
  for (const piece of target.split("/")) {
    if (piece === "" || piece === ".") continue;
    if (piece === "..") {
      if (parts.length === 0) return null;
      parts.pop();
    } else parts.push(piece);
  }
  return parts.join("/");
}


function mathBlock(state: StateBlock, start: number, end: number, silent: boolean): boolean {
  const first = state.bMarks[start] + state.tShift[start];
  if (state.src.slice(first, first + 2) !== "$$") return false;
  let line = start;
  let content = state.src.slice(first + 2, state.eMarks[start]);
  let closed = content.trimEnd().endsWith("$$") && content.trim().length > 2;
  if (closed) content = content.trimEnd().slice(0, -2);
  while (!closed && ++line < end) {
    const text = state.src.slice(state.bMarks[line] + state.tShift[line], state.eMarks[line]);
    if (text.trimEnd().endsWith("$$")) {
      content += "\n" + text.trimEnd().slice(0, -2);
      closed = true;
    } else content += "\n" + text;
  }
  if (!closed) return false;
  if (silent) return true;
  const token = state.push("math_block", "div", 0);
  token.content = content.trim();
  token.map = [start, line + 1];
  state.line = line + 1;
  return true;
}

function mathInline(state: StateInline, silent: boolean): boolean {
  const src = state.src;
  if (src[state.pos] !== "$" || src[state.pos + 1] === "$" || /\s/.test(src[state.pos + 1] ?? " ")) return false;
  let end = state.pos + 1;
  while ((end = src.indexOf("$", end)) !== -1 && (src[end - 1] === "\\" || /\s/.test(src[end - 1]))) end++;
  if (end === -1 || end === state.pos + 1) return false;
  if (!silent) state.push("math_inline", "span", 0).content = src.slice(state.pos + 1, end);
  state.pos = end + 1;
  return true;
}

export function renderer(): MarkdownIt {
  const md = new MarkdownIt({ html: false, linkify: false, typographer: false });
  md.block.ruler.before("fence", "math_block", mathBlock, { alt: ["paragraph"] });
  md.inline.ruler.before("escape", "math_inline", mathInline);
  const esc = md.utils.escapeHtml;
  md.renderer.rules.math_block = (t, i) => `<div class="math display" data-tex="${esc(t[i].content)}"></div>\n`;
  md.renderer.rules.math_inline = (t, i) => `<span class="math" data-tex="${esc(t[i].content)}"></span>`;

  const fence = md.renderer.rules.fence!;
  md.renderer.rules.fence = (tokens, i, options, env, self) =>
    tokens[i].info.trim() === "mermaid"
      ? `<div class="mermaid-block" data-code="${esc(tokens[i].content)}"></div>\n`
      : fence(tokens, i, options, env, self);

  md.renderer.rules.heading_open = (tokens, i, options, env: RenderEnv, self) => {
    const anchor = env.anchors[env.heading++];
    if (anchor) tokens[i].attrSet("id", anchor);
    return self.renderToken(tokens, i, options);
  };

  md.renderer.rules.link_open = (tokens, i, options, env: RenderEnv, self) => {
    const token = tokens[i];
    const href = token.attrGet("href") ?? "";
    if (/^https?:\/\//i.test(href)) {
      token.attrSet("target", "_blank");
      token.attrSet("rel", "noopener noreferrer");
      env.spans.push(false);
      return self.renderToken(tokens, i, options);
    }
    const [target, at] = href.split("#", 2);
    const doc = target === "" ? env.path : resolvePath(env.path, decodeURI(target));
    if (doc !== null && env.documents.has(doc)) {
      token.attrSet("href", fragment({ doc, at }));
      env.spans.push(false);
      return self.renderToken(tokens, i, options);
    }
    env.spans.push(true);  // another file of the repository: its path, not followed
    return `<span class="repo-path" title="${esc(doc ?? href)}">`;
  };
  md.renderer.rules.link_close = (tokens, i, options, env: RenderEnv, self) =>
    env.spans.pop() ? "</span>" : self.renderToken(tokens, i, options);

  md.renderer.rules.image = (tokens, i, _options, env: RenderEnv) => {
    const token = tokens[i];
    const src = resolvePath(env.path, token.attrGet("src") ?? "");
    return `<img class="document__image" data-src="${esc(src ?? "")}" alt="${esc(token.content)}">`;
  };
  return md;
}
