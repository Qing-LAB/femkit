import { useEffect, useMemo, useRef } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";
import type { Document as DocumentPart } from "../generated/schemas";
import { server } from "../kernel/client";
import { adopt } from "../kernel/styles";
import { scheme } from "../kernel/theme";
import { renderer, RenderEnv } from "./markdown";
import "./Document.css";

// One of the repository's documents (web.md § 2.3), rendered as GitHub does — tables, code, math,
// Mermaid diagrams — its links followed within the viewer, nothing able to reach beyond the
// documents the server lists. A diagram's and a formula's styles reach the page through its object
// model, never as inline style text (§ 5).

async function decorate(root: HTMLElement): Promise<void> {
  root.querySelectorAll<HTMLElement>(".math").forEach((el) => {
    katex.render(el.dataset.tex ?? "", el, { displayMode: el.classList.contains("display"), throwOnError: false, trust: false });
  });
  root.querySelectorAll<HTMLImageElement>("img.document__image[data-src]").forEach(async (img) => {
    const got = await server.document(img.dataset.src ?? "");
    if (got.kind === "ok" && "data" in got.value) img.src = `data:${got.value.type};base64,${got.value.data}`;
  });
  const blocks = [...root.querySelectorAll<HTMLElement>(".mermaid-block")];
  if (!blocks.length) return;
  const mermaid = (await import("mermaid")).default;
  mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: scheme() === "dark" ? "dark" : "default",
                       htmlLabels: false, flowchart: { htmlLabels: false } });
  for (const [n, block] of blocks.entries()) {
    try {
      const code = (block.dataset.code ?? "").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
        .replace(/&quot;/g, '"').replace(/&amp;/g, "&");
      const { svg } = await mermaid.render(`diagram-${Date.now()}-${n}`, code);
      const parsed = new DOMParser().parseFromString(svg, "text/html");
      const css = [...parsed.querySelectorAll("style")].map((s) => { const t = s.textContent ?? ""; s.remove(); return t; });
      adopt(css.join("\n"));
      const drawn = parsed.querySelector("svg");
      if (!drawn) throw new Error("no drawing came back");
      const node = document.importNode(drawn, true) as unknown as SVGElement;
      const styled = [node, ...node.querySelectorAll<SVGElement>("[style]")].filter((el) => el.hasAttribute("style"));
      const values = styled.map((el) => el.getAttribute("style") ?? "");
      styled.forEach((el) => el.removeAttribute("style"));
      block.replaceChildren(node);
      styled.forEach((el, k) => { el.style.cssText = values[k]; });
    } catch (e) {
      block.classList.add("document__broken");
      block.textContent = String(e);
    }
  }
}

export function Document({ document: doc, documents, at }: { document: DocumentPart; documents: string[]; at?: string }) {
  const body = useRef<HTMLDivElement>(null);
  const md = useMemo(renderer, []);
  const html = useMemo(() => {
    const env: RenderEnv = { path: doc.path, anchors: doc.headings.map((h) => h.anchor),
                             documents: new Set(documents), heading: 0, spans: [] };
    return md.render(doc.text, env);
  }, [doc, documents, md]);
  useEffect(() => {
    if (body.current) void decorate(body.current).catch(() => undefined);
    window.document.title = doc.headings[0]?.text ?? doc.path;
  }, [html]);
  useEffect(() => {
    const target = at ? window.document.getElementById(at) : null;
    (target ?? body.current)?.scrollIntoView({ block: "start" });
  }, [html, at]);
  return <article className="document" ref={body} dangerouslySetInnerHTML={{ __html: html }} />;
}
