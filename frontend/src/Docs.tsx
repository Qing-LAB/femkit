import { useEffect, useMemo, useRef, useState } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";
import { docImage, docsList, DocText, docText, hasToken, NeedToken, Refused } from "./api";
import { docHash, renderer, RenderEnv } from "./markdown";

// The document viewer (api.md § 5.2): the repository's documents as a tree of folders, each
// rendered as GitHub does, links followed within the viewer, nothing able to reach beyond them.

interface Folder { name: string; path: string; folders: Map<string, Folder>; files: string[] }

function tree(paths: string[]): Folder {
  const root: Folder = { name: "", path: "", folders: new Map(), files: [] };
  for (const path of paths) {
    const parts = path.split("/");
    let node = root;
    parts.slice(0, -1).forEach((part, i) => {
      if (!node.folders.has(part)) {
        node.folders.set(part, { name: part, path: parts.slice(0, i + 1).join("/"), folders: new Map(), files: [] });
      }
      node = node.folders.get(part)!;
    });
    node.files.push(path);
  }
  return root;
}

function where(): { doc: string; at: string } {
  const params = new URLSearchParams(window.location.hash.slice(1));
  return { doc: params.get("doc") ?? "docs/README.md", at: params.get("at") ?? "" };
}

function ancestors(path: string): string[] {
  const parts = path.split("/");
  return parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join("/"));
}

function FolderView({ folder, open, toggle, current }: {
  folder: Folder; open: Set<string>; toggle: (p: string) => void; current: string;
}) {
  return (
    <ul className="tree">
      {[...folder.folders.values()].sort((a, b) => a.name.localeCompare(b.name)).map((f) => (
        <li key={f.path}>
          <button className="tree-folder" aria-expanded={open.has(f.path)} onClick={() => toggle(f.path)}>
            <span className="caret" aria-hidden="true">{open.has(f.path) ? "▾" : "▸"}</span>{f.name}/
          </button>
          {open.has(f.path) && <FolderView folder={f} open={open} toggle={toggle} current={current} />}
        </li>
      ))}
      {folder.files.map((file) => (
        <li key={file}>
          <a className={`tree-file ${file === current ? "active" : ""}`} href={docHash(file)}>{file.split("/").pop()}</a>
        </li>
      ))}
    </ul>
  );
}

async function decorate(root: HTMLElement, dark: boolean): Promise<void> {
  root.querySelectorAll<HTMLElement>(".math").forEach((el) => {
    katex.render(el.dataset.tex ?? "", el, { displayMode: el.classList.contains("display"), throwOnError: false,
                                             trust: false });
  });
  root.querySelectorAll<HTMLImageElement>("img.doc-image[data-src]").forEach(async (img) => {
    const data = await docImage(img.dataset.src ?? "");
    if (data) img.src = data;
  });
  const blocks = [...root.querySelectorAll<HTMLElement>(".mermaid-block")];
  if (!blocks.length) return;
  const mermaid = (await import("mermaid")).default;
  // Labels as SVG text, not HTML inside the drawing: no markup to parse, no inline styles to carry.
  mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: dark ? "dark" : "default",
                       htmlLabels: false, flowchart: { htmlLabels: false } });
  for (const [n, block] of blocks.entries()) {
    try {
      // A label's entities as GitHub's HTML labels show them: `&lt;study&gt;` reads `<study>`.
      const code = (block.dataset.code ?? "").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
        .replace(/&quot;/g, '"').replace(/&amp;/g, "&");
      const { svg } = await mermaid.render(`diagram-${Date.now()}-${n}`, code);
      const parsed = new DOMParser().parseFromString(svg, "text/html");  // tolerant of any markup in labels
      // Its styles through the page's object model, never as inline style text (api.md § 5.5).
      const css = [...parsed.querySelectorAll("style")].map((s) => { const t = s.textContent ?? ""; s.remove(); return t; });
      const sheet = new CSSStyleSheet();
      sheet.replaceSync(css.join("\n"));
      document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
      const drawn = parsed.querySelector("svg");
      if (!drawn) throw new Error("no drawing came back");
      const node = document.importNode(drawn, true) as unknown as SVGElement;
      const styled = [node, ...node.querySelectorAll<SVGElement>("[style]")].filter((el) => el.hasAttribute("style"));
      const values = styled.map((el) => el.getAttribute("style") ?? "");
      styled.forEach((el) => el.removeAttribute("style"));
      block.replaceChildren(node);
      styled.forEach((el, k) => { el.style.cssText = values[k]; });
    } catch (e) {
      block.classList.add("diagram-error");
      block.textContent = `this diagram does not render: ${String(e)}`;
    }
  }
}

export function DocsApp() {
  const [files, setFiles] = useState<string[] | null>(null);
  const [place, setPlace] = useState(where());
  const [doc, setDoc] = useState<DocText | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<Set<string>>(new Set(["docs", ...ancestors(where().doc)]));
  const body = useRef<HTMLDivElement>(null);
  const md = useMemo(renderer, []);
  const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;

  useEffect(() => {
    docsList().then(setFiles).catch((e) => setError(e instanceof NeedToken
      ? "This tab has no access token: open the viewer from the femkit page." : String(e)));
    const onHash = () => setPlace(where());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    setOpen((o) => new Set([...o, ...ancestors(place.doc)]));
    if (doc?.path === place.doc) return;
    setDoc(null);
    docText(place.doc).then(setDoc).catch((e) => setError(e instanceof Refused ? e.message : String(e)));
  }, [place.doc]);

  const html = useMemo(() => {
    if (!doc || !files) return "";
    const env: RenderEnv = { path: doc.path, anchors: doc.headings.map((h) => h.anchor),
                             documents: new Set(files), heading: 0, spans: [] };
    return md.render(doc.text, env);
  }, [doc, files, md]);

  useEffect(() => {
    if (!body.current || !html) return;
    decorate(body.current, dark).catch(() => undefined);
    document.title = `${doc?.headings[0]?.text ?? doc?.path} — femkit`;
  }, [html]);

  useEffect(() => {
    if (!html) return;
    const target = place.at ? document.getElementById(place.at) : null;
    (target ?? body.current)?.scrollIntoView({ block: "start" });
  }, [html, place.at]);

  if (!hasToken() && !files) {
    return <div className="gate"><h1>femkit documents</h1><p>Open the viewer from the femkit page: it hands this tab
      its access token.</p></div>;
  }
  const toggle = (p: string) => setOpen((o) => { const n = new Set(o); n.has(p) ? n.delete(p) : n.add(p); return n; });
  return (
    <div className="shell docs-shell">
      <aside className="sidebar">
        <div className="brand">femkit documents</div>
        <nav>{files && <FolderView folder={tree(files)} open={open} toggle={toggle} current={place.doc} />}</nav>
      </aside>
      <main>
        {error && <div className="card result not-ok"><p>{error}</p></div>}
        {!doc && !error && <p className="muted">Loading…</p>}
        <article className="doc" ref={body} dangerouslySetInnerHTML={{ __html: html }} />
      </main>
    </div>
  );
}
