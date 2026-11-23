import { useCallback, useEffect, useMemo, useState } from "react";
import { hasToken, NeedToken, OperationInfo, operations, runOperation, setToken, viewerAddress } from "./api";
import { ModelWorkspace } from "./ModelWorkspace";
import { command, OperationView } from "./OperationView";
import { Change, PlanApply } from "./plan";

// The page (api.md § 5.2.2): one top bar — the project, the study, an environment — over three
// workspaces: Model, Runs and Operations; the documents in a tab of their own.

function group(name: string): string {
  return name.includes(".") ? name.split(".")[0] : "femkit";
}

function TokenGate({ onToken }: { onToken: () => void }) {
  const [value, setValue] = useState("");
  return (
    <div className="gate">
      <h1>femkit</h1>
      <p>This server needs its access token. Open the address <code>serve start</code> printed, or paste the
        token here; it is kept only in this tab.</p>
      <form onSubmit={(e) => { e.preventDefault(); setToken(value.trim()); onToken(); }}>
        <input type="password" autoComplete="off" value={value} onChange={(e) => setValue(e.target.value)}
          placeholder="token" spellCheck={false} />
        <button className="primary" type="submit" disabled={!value.trim()}>Continue</button>
      </form>
    </div>
  );
}

function OperationsWorkspace() {
  const [ops, setOps] = useState<OperationInfo[] | null>(null);
  const [needToken, setNeedToken] = useState(!hasToken());
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    operations()
      .then((list) => { setOps(list); setNeedToken(false); setSelected((s) => s ?? list[0]?.name ?? null); })
      .catch((e) => (e instanceof NeedToken ? setNeedToken(true) : setError(String(e))));
  };
  useEffect(() => { if (!needToken) load(); }, [needToken]);

  const groups = useMemo(() => {
    const out = new Map<string, OperationInfo[]>();
    for (const op of ops ?? []) {
      if (filter && !`${op.name} ${op.description}`.toLowerCase().includes(filter.toLowerCase())) continue;
      out.set(group(op.name), [...(out.get(group(op.name)) ?? []), op]);
    }
    return out;
  }, [ops, filter]);

  if (needToken) return <p className="muted">This page has no access token.</p>;
  const op = ops?.find((o) => o.name === selected) ?? null;
  return (
    <div className="shell workspace-shell">
      <aside className="sidebar">
        <div className="brand">femkit</div>
        <input className="search" type="search" placeholder="Find an operation" value={filter}
          onChange={(e) => setFilter(e.target.value)} />
        <nav>
          {[...groups].map(([g, list]) => (
            <div className="group" key={g}>
              <div className="group-name">{g}</div>
              {list.map((o) => (
                <button key={o.name} className={`nav-item ${o.name === selected ? "active" : ""}`}
                  onClick={() => setSelected(o.name)} title={command(o.name)}>
                  <span>{o.name.includes(".") ? o.name.split(".").slice(1).join(" ") : o.name}</span>
                  {o.changes && <span className="dot" aria-label="changes things" />}
                </button>
              ))}
            </div>
          ))}
        </nav>
      </aside>
      <main>
        {error && <div className="card result not-ok"><p>{error}</p></div>}
        {!ops && !error && <p className="muted">Loading…</p>}
        {op && <OperationView op={op} onNeedToken={() => setNeedToken(true)} />}
      </main>
    </div>
  );
}


function stored(key: string): string {
  try { return localStorage.getItem(key) ?? ""; } catch { return ""; }
}

function store(key: string, value: string): void {
  try { localStorage.setItem(key, value); } catch { /* a convenience only */ }
}

function RunsWorkspace({ project, study, onNeedToken }: { project: string; study: string | null; onNeedToken: () => void }) {
  const [cases, setCases] = useState<any[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Change | null>(null);
  const load = () => runOperation("case.list", { project }).then(({ result }) => { setCases(result.cases); setError(null); })
    .catch((e) => (e instanceof NeedToken ? onNeedToken() : setError(String(e?.message || e))));
  useEffect(() => { setCases(null); setPending(null); load(); }, [project, study]);
  return (
    <section className="runs">
      <div className="card">
        <h2>Cases</h2>
        {study && !pending && <div className="actions"><button onClick={() => setPending({ operation: "study.expand",
          request: { project, study }, title: `expand the study ${study}` })}>Expand {study}</button></div>}
        {pending && <PlanApply key={JSON.stringify(pending)} change={pending} onCancel={() => setPending(null)} onDone={() => { setPending(null); load(); }} />}
        {error && <p className="problems">{error}</p>}
        {cases && (cases.length === 0 ? <p className="muted">No case is written yet.</p> : (
          <div className="table-wrap"><table>
            <thead><tr><th>case</th><th>studies</th><th>axis values</th></tr></thead>
            <tbody>{cases.map((c) => (
              <tr key={c.id}><td><code>{c.id.slice(0, 12)}</code></td><td>{c.studies.join(", ")}</td>
                <td>{Object.entries(c.point).map(([k, v]) => `${k} = ${v}`).join(", ") || "—"}</td></tr>))}
            </tbody></table></div>))}
        <p className="muted">Preparation, jobs and results arrive with M3, M4 and M6 (plan § 3).</p>
      </div>
    </section>
  );
}

export function App() {
  const [needToken, setNeedToken] = useState(!hasToken());
  const [workspace, setWorkspace] = useState<"model" | "runs" | "operations">("model");
  // A project named in the address's fragment (`#project=/path`) opens it, as `doc=` does in the viewer.
  const named = new URLSearchParams(window.location.hash.slice(1)).get("project") ?? stored("femkit-project");
  const [draft, setDraft] = useState(named);
  const [project, setProject] = useState(named);
  const [studies, setStudies] = useState<string[]>([]);
  const [study, setStudy] = useState<string | null>(null);
  const lostToken = useCallback(() => setNeedToken(true), []);   // one function: a workspace's loader depends on it
  if (needToken) return <TokenGate onToken={() => setNeedToken(false)} />;
  const open = () => { setProject(draft.trim()); store("femkit-project", draft.trim()); setStudy(null); };
  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">femkit</span>
        <form className="topbar-field" onSubmit={(e) => { e.preventDefault(); open(); }}>
          <label>project</label>
          <input value={draft} placeholder="/path/to/a/project" spellCheck={false} onChange={(e) => setDraft(e.target.value)} />
          <button type="submit">Open</button>
        </form>
        <span className="topbar-field"><label>study</label>
          <select value={study ?? ""} onChange={(e) => setStudy(e.target.value || null)}>
            <option value="">—</option>{studies.map((s) => <option key={s}>{s}</option>)}
          </select></span>
        <span className="topbar-field"><label>environment</label>
          <select disabled title="the match overlay arrives with abilities and the match report (plan § 3, M5 step 3)">
            <option>—</option></select></span>
        <nav className="workspaces">
          {(["model", "runs", "operations"] as const).map((w) => (
            <button key={w} className={w === workspace ? "active" : ""} onClick={() => setWorkspace(w)}>
              {w[0].toUpperCase() + w.slice(1)}</button>))}
        </nav>
        <button className="quiet" onClick={() => window.open(viewerAddress(), "_blank", "noopener")}>Documents ↗</button>
      </header>
      <div className="workspace">
        {workspace === "model" && (project
          ? <ModelWorkspace project={project} study={study} onStudies={setStudies} onNeedToken={lostToken} />
          : <p className="muted pad">Open a project folder: the model is its model.toml. An empty folder starts a new model.</p>)}
        {workspace === "runs" && (project ? <RunsWorkspace project={project} study={study} onNeedToken={lostToken} />
          : <p className="muted pad">Open a project folder first.</p>)}
        {workspace === "operations" && <OperationsWorkspace />}
      </div>
    </div>
  );
}
