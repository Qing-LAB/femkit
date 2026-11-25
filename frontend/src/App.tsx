import { useCallback, useEffect, useMemo, useState } from "react";
import { hasToken, NeedToken, OperationInfo, operations, setToken, viewerAddress } from "./api";
import { Notifications } from "./elements/Notifications";
import { Registry } from "./kernel/action";
import { OperationView } from "./OperationView";

// The first page: the Operations workspace and the documents, until the page is rebuilt on the
// kernel and elements (web.md § 2.2; plan § 4, G).

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

function OperationsWorkspace({ onNeedToken }: { onNeedToken: () => void }) {
  const [ops, setOps] = useState<OperationInfo[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    operations()
      .then((list) => { setOps(list); setSelected((s) => s ?? list[0]?.name ?? null); })
      .catch((e) => (e instanceof NeedToken ? onNeedToken() : setError(String(e))));
  }, [onNeedToken]);

  const groups = useMemo(() => {
    const out = new Map<string, OperationInfo[]>();
    for (const op of ops ?? []) {
      if (filter && !`${op.name} ${op.description}`.toLowerCase().includes(filter.toLowerCase())) continue;
      out.set(group(op.name), [...(out.get(group(op.name)) ?? []), op]);
    }
    return out;
  }, [ops, filter]);

  const registry = useMemo(() => new Map((ops ?? []).map((o) => [o.name, o] as const)), [ops]);   // what every action runs by
  const op = ops?.find((o) => o.name === selected) ?? null;
  return (
    <Registry.Provider value={registry}>
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
                    onClick={() => setSelected(o.name)} title={o.name}>
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
          {op && <OperationView op={op} onNeedToken={onNeedToken} />}
        </main>
      </div>
    </Registry.Provider>
  );
}


export function App() {
  const [needToken, setNeedToken] = useState(!hasToken());
  const lostToken = useCallback(() => setNeedToken(true), []);   // one function: the workspace's loader depends on it
  if (needToken) return <TokenGate onToken={() => setNeedToken(false)} />;
  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">femkit</span>
        <nav className="workspaces"><button className="active">Operations</button></nav>
        <button className="quiet" onClick={() => window.open(viewerAddress(), "_blank", "noopener")}>Documents ↗</button>
      </header>
      <div className="workspace"><OperationsWorkspace onNeedToken={lostToken} /></div>
      <Notifications />
    </div>
  );
}
