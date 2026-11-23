import { useEffect, useMemo, useState } from "react";
import { hasToken, NeedToken, OperationInfo, operations, setToken } from "./api";
import { command, OperationView } from "./OperationView";

// The page: every registered operation, grouped as the command line groups them, built from
// the registry alone (api.md § 5.2). The model graph view comes with `model graph` (plan § 3, M7).

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

export function App() {
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

  if (needToken) return <TokenGate onToken={() => setNeedToken(false)} />;
  const op = ops?.find((o) => o.name === selected) ?? null;
  return (
    <div className="shell">
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
        <div className="sidebar-foot">
          <span className="muted">Model graph — arrives with <code>model graph</code> (M5)</span>
        </div>
      </aside>
      <main>
        {error && <div className="card result not-ok"><p>{error}</p></div>}
        {!ops && !error && <p className="muted">Loading…</p>}
        {op && <OperationView op={op} onNeedToken={() => setNeedToken(true)} />}
      </main>
    </div>
  );
}
