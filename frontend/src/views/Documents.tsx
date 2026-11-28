import { useEffect, useState } from "react";
import type { Document as DocumentPart } from "../generated/schemas";
import bundle from "../generated/bundle.json";
import { server } from "../kernel/client";
import { useDeclared } from "../kernel/declared";
import { Banner } from "../elements/Banner";
import { Document } from "../elements/Document";
import { Empty } from "../elements/Empty";
import { fragment, place as here } from "../kernel/documents";
import "./Documents.css";

// The document viewer (web.md § 2.3), in a tab of its own: the repository's documents as a tree of
// folders that open and close, and the one chosen, rendered. It only arranges: the tree and the
// document are the server's.

interface Folder { name: string; path: string; folders: Map<string, Folder>; files: string[] }

function tree(paths: string[]): Folder {
  const root: Folder = { name: "", path: "", folders: new Map(), files: [] };
  for (const path of paths) {
    const parts = path.split("/");
    let node = root;
    parts.slice(0, -1).forEach((part, i) => {
      if (!node.folders.has(part)) node.folders.set(part, { name: part, path: parts.slice(0, i + 1).join("/"), folders: new Map(), files: [] });
      node = node.folders.get(part)!;
    });
    node.files.push(path);
  }
  return root;
}

/** The document and section the address names, the declaration's first document where none. */
function where(first: string): { doc: string; at: string } {
  const named = here();
  return { doc: named.doc ?? first, at: named.at ?? "" };
}

function ancestors(path: string): string[] {
  const parts = path.split("/");
  return parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join("/"));
}

function FolderView({ folder, open, toggle, current }: { folder: Folder; open: Set<string>; toggle: (p: string) => void; current: string }) {
  return (
    <ul className="documents__tree">
      {[...folder.folders.values()].sort((a, b) => a.name.localeCompare(b.name)).map((f) => (
        <li key={f.path}>
          <button type="button" className="documents__folder" aria-expanded={open.has(f.path)} onClick={() => toggle(f.path)}>
            {f.name}/
          </button>
          {open.has(f.path) && <FolderView folder={f} open={open} toggle={toggle} current={current} />}
        </li>
      ))}
      {folder.files.map((file) => (
        <li key={file}>
          <a className={`documents__file ${file === current ? "documents__file--current" : ""}`} href={fragment({ doc: file })}>
            {file.split("/").pop()}
          </a>
        </li>
      ))}
    </ul>
  );
}

export function Documents() {
  const { page } = useDeclared();
  const [files, setFiles] = useState<string[] | null>(null);
  const [place, setPlace] = useState(where(page.documents.first));
  const [doc, setDoc] = useState<DocumentPart | null>(null);
  const [lost, setLost] = useState<string | null>(null);
  const [open, setOpen] = useState<Set<string>>(new Set());

  useEffect(() => {
    void server.documents().then((o) => {
      if (o.kind === "ok") return setFiles(o.value.files);
      setLost(o.kind === "refused" ? o.refusal.message : bundle.gate.says[o.kind === "unreachable" ? "unreachable" : "unreadable"]);
    });
    const onHash = () => setPlace(where(page.documents.first));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    if (!place.doc) return;
    setOpen((o) => new Set([...o, ...ancestors(place.doc)]));
    if (doc?.path === place.doc) return;
    void server.document(place.doc).then((o) => {
      if (o.kind === "ok" && "text" in o.value) setDoc(o.value);
      else setLost(o.kind === "refused" ? o.refusal.message : bundle.gate.says.unreadable);
    });
  }, [place.doc]);

  const toggle = (p: string) => setOpen((o) => { const n = new Set(o); if (n.has(p)) n.delete(p); else n.add(p); return n; });
  return (
    <div className="documents">
      <aside className="documents__side">
        <Banner app={page.app} />
        <nav className="documents__nav">{files && <FolderView folder={tree(files)} open={open} toggle={toggle} current={place.doc} />}</nav>
      </aside>
      <main className="documents__main">
        {lost && <Empty icon={page.controls.documents.icon ?? undefined} title={lost} />}
        {!doc && !lost && <Empty title={page.says.loading} />}
        {doc && files && <Document document={doc} documents={files} at={place.at} />}
      </main>
    </div>
  );
}
