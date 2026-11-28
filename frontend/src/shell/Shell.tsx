import { useCallback, useEffect, useState } from "react";
import { hasToken, onToken, Outcome, server, setToken, viewerAddress } from "../kernel/client";
import { Recover } from "./Recover";
import { Declaration, type Declared, useDeclared } from "../kernel/declared";
import { keep } from "../kernel/notify";
import bundle from "../generated/bundle.json";
import { go, usePage, WORKSPACE } from "../kernel/state";
import { Banner } from "../elements/Banner";
import { Icon } from "../elements/Icon";
import { Notifications } from "../elements/Notifications";
import { Flows } from "../elements/ActionButton";
import { Sentence } from "../elements/Sentence";
import { Tabs } from "../elements/Tabs";
import { Documents } from "../views/Documents";
import { Operations } from "../views/Operations";
import { Workspace } from "../views/Workspace";
import { ThemeSwitch } from "./ThemeSwitch";
import "./Shell.css";

// The shell (web.md § 9.4): it reads the declaration and the operations once, then draws the top bar
// — the mark, the workspaces from the declaration, the theme switch, the documents — the workspace in
// view, and the notifications. A workspace showing a document is drawn by the document workspace; one
// showing none, the registry itself, by the Operations view (web.md § 8.1). The document viewer is the
// same bundle at /docs (§ 2.3).

type Lost = "token" | "unreachable" | "unreadable";

/** Asking for the token (web.md § 5): before it, nothing the server declares can be read, so the gate's
 *  words, icon and mark are the bundle's own, generated beside the declaration — and what it says when
 *  the server does not answer, or answers what the page cannot read. */
function TokenGate({ lost }: { lost: Lost }) {
  const [value, setValue] = useState("");
  const gate = bundle.gate;
  return (
    <form className="shell__gate" onSubmit={(e) => { e.preventDefault(); setToken(value.trim()); }}>
      <img className="shell__gate-mark" src={bundle.mark} alt="" />
      <p className="shell__gate-says"><Sentence text={gate.says[lost]} /></p>
      <label className="shell__gate-field">
        <span>{gate.label}</span>
        <input type="password" autoComplete="off" spellCheck={false} value={value} onChange={(e) => setValue(e.target.value)} />
      </label>
      <button type="submit" className="shell__gate-go" disabled={!value.trim()} title={gate.help} aria-label={gate.help}>
        <Icon name={gate.icon} />
      </button>
    </form>
  );
}

function Bar() {
  const { page } = useDeclared();
  const state = usePage();
  const chosen = state[WORKSPACE] ?? page.workspaces[0].key;
  const docs = page.controls.documents;
  return (
    <header className="shell__bar">
      <Banner app={page.app} />
      <Tabs label={page.app.name} chosen={chosen} choose={(key) => go({ [WORKSPACE]: key })}
            tabs={page.workspaces.map((w) => ({ key: w.key, label: w.title, icon: w.icon, title: w.tagline }))} />
      <span className="shell__spacer" />
      <ThemeSwitch page={page} />
      <a className="shell__documents" href={viewerAddress({ doc: page.documents.first })} target="_blank" rel="noopener" title={docs.help}>
        <Icon name={docs.icon} size="sm" /><span>{docs.label}</span>
      </a>
    </header>
  );
}

function Page() {
  const { page } = useDeclared();
  const state = usePage();
  const workspace = page.workspaces.find((w) => w.key === state[WORKSPACE]) ?? page.workspaces[0];
  return (
    <div className="shell">
      <Bar />
      <main className="shell__main">
        <Recover key={workspace.key}>
          {workspace.document ? <Workspace key={workspace.key} workspace={workspace} />
                              : <Operations key={workspace.key} workspace={workspace} />}
        </Recover>
      </main>
      <Flows />
      <Notifications />
    </div>
  );
}

export function Shell() {
  const [declared, setDeclared] = useState<Declared | null>(null);
  const [lost, setLost] = useState<Lost | null>(hasToken() ? null : "token");
  const load = useCallback(async () => {
    const [page, operations] = await Promise.all([server.page(), server.operations()]);
    const failed = [page, operations].find((o): o is Exclude<Outcome<never>, { kind: "ok" }> => o.kind !== "ok");
    if (failed) return setLost(failed.kind === "token" ? "token" : failed.kind === "unreachable" ? "unreachable" : "unreadable");
    if (page.kind === "ok" && operations.kind === "ok") {
      keep(page.value.notices);
      setDeclared({ page: page.value, operations: new Map(operations.value.map((o) => [o.name, o])) });
      setLost(null);
    }
  }, []);
  useEffect(() => { if (!lost) void load(); }, [lost, load]);
  // A token the server refuses, from any route the page asks, brings back the gate; a new one, the page.
  useEffect(() => onToken(() => setLost("token"), () => setLost(null)), []);
  if (lost) return <TokenGate lost={lost} />;
  if (!declared) return null;
  return (
    <Declaration.Provider value={declared}>
      {window.location.pathname.startsWith(bundle.addresses.documents) ? <Documents /> : <Page />}
    </Declaration.Provider>
  );
}
