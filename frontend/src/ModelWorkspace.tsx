import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background, Connection, Controls, Edge, Handle, MiniMap, Node, NodeProps, Position, ReactFlow,
  useEdgesState, useNodesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { apply, lines, NeedToken, planOperation, runOperation, viewerAddress } from "./api";
import { Change, PlanApply } from "./plan";
import { setCommand } from "./toml";

// The Model workspace (api.md § 5.2.2), drawn from the graph document `model graph` returns
// (models.md § 11.2) — its nodes with their fields and typed ports, its edges, its palette and its
// choices — and naming no field of its own; every change a plan, shown and applied with its digest.

interface Field { name: string; address: string; text: string }
interface Port { name: string; address: string; accepts: string[]; many: boolean; names: string[] }
interface GraphNode { address: string; kind: string; type: string | null; label: string; name: string | null;
  rank: number; renamable: boolean; fields: Field[]; ports: Port[]; findings: any[]; position: number[] | null }
interface GraphEdge { source: string; target: string; port: string; type: string; address: string;
  held: "key" | "value" | "item" | "text" }
interface Entry { group: string; kind: string; description: string; section: string | null; on: string[];
  parameters: Record<string, string>; address: string; names: Record<string, string[]>; needs: string | null;
  template: string }
interface Choice { address: string; label: string; description: string; value: string | null; options: string[] }
interface Graph { formulation: string | null; choices: Choice[]; studies: string[]; science: string | null;
  nodes: GraphNode[]; edges: GraphEdge[]; palette: Entry[]; issues: any[] }

// A name as a TOML string. Names are bare words (models.md § 3), which JSON and TOML write alike.
const quoted = (name: string) => JSON.stringify(name);
const takes = (accepts: string[], n: GraphNode) => accepts.includes(n.kind) || accepts.includes(`${n.kind}:${n.type}`);

/** The port of ``from`` that a wire to ``to`` is drawn into: one that accepts it and does not hold it yet. */
function portFor(from: GraphNode | undefined, to: GraphNode | undefined): Port | null {
  if (!from || !to || !to.name) return null;
  return from.ports.find((p) => takes(p.accepts, to) && !p.names.includes(to.name!)) ?? null;
}

/** A wire drawn between two nodes, either way: the port that holds it, and the node it names. */
function between(a: GraphNode | undefined, b: GraphNode | undefined): { port: Port; to: GraphNode } | null {
  const forward = portFor(a, b);
  if (forward) return { port: forward, to: b! };
  const back = portFor(b, a);
  return back ? { port: back, to: a! } : null;
}

function wired(project: string, p: Port, to: GraphNode): Change {
  const value = p.many ? `[${[...p.names, to.name!].map(quoted).join(", ")}]` : quoted(to.name!);
  return { operation: "model.set", request: { project, address: p.address, value }, title: `${p.address}: ${to.name}` };
}

/** The edit that removes a wire, by how its reference is held (models.md § 11.2). */
function cut(project: string, from: GraphNode | undefined, to: GraphNode | undefined, e: GraphEdge): Change | string {
  if (e.held === "text") return `${to?.label ?? e.target} is used inside the value at ${e.address}: change that value`;
  if (e.held === "item") {
    const p = from?.ports.find((q) => e.address.startsWith(q.address + "."));
    if (!p || !to?.name) return `the list holding ${e.address} has no port: change it in the inspector`;
    const rest = p.names.filter((n) => n !== to.name);
    return rest.length > 0
      ? { operation: "model.set", request: { project, address: p.address, value: `[${rest.map(quoted).join(", ")}]` },
          title: `take ${to.name} out of ${p.address}` }
      : { operation: "model.unset", request: { project, address: p.address }, title: `remove ${p.address}` };
  }
  return { operation: "model.unset", request: { project, address: e.address }, title: `remove ${e.address}` };
}

function FemNode({ data, selected }: NodeProps) {
  const n = data.node as GraphNode;
  return (
    <div className={`fem-node kind-${n.kind} ${selected ? "selected" : ""} ${n.findings.length ? "faulty" : ""}`}>
      <Handle type="target" position={Position.Left} />
      <div className="fem-node-kind">{n.kind}{n.type ? `: ${n.type}` : ""}</div>
      <div className="fem-node-label">{n.label}</div>
      {n.findings.length > 0 && <div className="fem-node-findings" title={n.findings.map((f) => f.message).join("\n")}>
        ● {n.findings.length}</div>}
      <Handle type="source" position={Position.Right}
        title={n.ports.map((p) => `${p.name}: ${p.accepts.join(" or ")}`).join("\n")} />
    </div>
  );
}
const nodeTypes = { fem: FemNode };

function layout(nodes: GraphNode[]): Node[] {
  const rows: Record<number, number> = {};
  return nodes.map((n) => {
    const row = (rows[n.rank] = (rows[n.rank] ?? -1) + 1);
    const position = n.position ? { x: n.position[0], y: n.position[1] } : { x: n.rank * 240, y: row * 96 };
    return { id: n.address, type: "fem", position, data: { node: n } };
  });
}

function Palette({ graph, choose }: { graph: Graph; choose: (e: Entry) => void }) {
  const groups = [...new Set(graph.palette.map((e) => e.group))];
  return (
    <div className="palette">
      {groups.map((g) => (
        <div className="palette-group" key={g}>
          <div className="group-name">{g}</div>
          {graph.palette.filter((e) => e.group === g).map((e) => (
            <button key={e.kind + e.address} className="palette-entry" title={e.needs ? `needs ${e.needs}` : e.description}
              disabled={!!e.needs} onClick={() => choose(e)}>
              <span>{e.kind.replace(/_/g, " ")}</span>
              {e.section && graph.science && (
                <a className="why" href={viewerAddress(graph.science, e.section)} target="_blank" rel="noopener noreferrer"
                   onClick={(ev) => ev.stopPropagation()} title="where it is defined">?</a>)}
            </button>
          ))}
        </div>
      ))}
      {!graph.formulation && <p className="muted">Choose a formulation (top of the inspector) for its kinds.</p>}
    </div>
  );
}

function AddForm({ graph, entry, project, change }: {
  graph: Graph; entry: Entry; project: string; change: (c: Change) => void;
}) {
  const [filled, setFilled] = useState<Record<string, string>>({});
  const [value, setValue] = useState(entry.template);
  const holes = Object.entries(entry.names);
  const address = holes.reduce((a, [h]) => a.replace(h, filled[h] || h), entry.address);
  return (
    <div className="inspector">
      <h3>Add {entry.kind.replace(/_/g, " ")}</h3>
      <p className="muted">{entry.description}</p>
      {Object.entries(entry.parameters).map(([p, d]) => <p key={p} className="param"><code>{p}</code> — {d}</p>)}
      {holes.map(([h, accepts]) => (
        <label key={h}>{h.slice(1, -1)}
          <input list={`names-${h}`} value={filled[h] ?? ""} spellCheck={false}
            placeholder={accepts.length ? accepts.join(" or ") : "a new name"}
            onChange={(e) => setFilled({ ...filled, [h]: e.target.value.trim() })} />
          <datalist id={`names-${h}`}>
            {graph.nodes.filter((n) => n.name && takes(accepts, n)).map((n) => <option key={n.address} value={n.name!} />)}
          </datalist></label>
      ))}
      <label>value<textarea rows={3} value={value} spellCheck={false} onChange={(e) => setValue(e.target.value)} /></label>
      <code className="address">{address}</code>
      <div className="actions">
        <button disabled={holes.some(([h]) => !filled[h])}
          onClick={() => change({ operation: "model.set", request: { project, address, value }, title: `set ${address}` })}>
          Add</button></div>
    </div>
  );
}

function ModelForm({ graph, project, change }: { graph: Graph; project: string; change: (c: Change) => void }) {
  return (
    <div className="inspector">
      <h3>Model</h3>
      {graph.choices.map((c) => (
        <label key={c.address} title={c.description}>{c.label}
          <select value={c.value ?? ""} onChange={(e) => change(e.target.value
            ? { operation: "model.set", request: { project, address: c.address, value: quoted(e.target.value) },
                title: `${c.label}: ${e.target.value}` }
            : { operation: "model.unset", request: { project, address: c.address }, title: `clear the ${c.label}` })}>
            <option value="">—</option>
            {c.options.map((o) => <option key={o}>{o}</option>)}
          </select></label>
      ))}
      <p className="muted">Select a node to see its fields, or pick an entry of the palette to add one.</p>
    </div>
  );
}

function NodeForm({ node, project, change }: { node: GraphNode; project: string; change: (c: Change) => void }) {
  // Each field as typed: the file's own text until edited; a finding's fix adds the field it names.
  const [typed, setTyped] = useState<Record<string, string>>({});
  const [rename, setRename] = useState("");
  const set = (address: string, value: string) =>
    change({ operation: "model.set", request: { project, address, value }, title: `set ${address}` });
  const rows: [string, string, string | null][] = [
    ...node.fields.map((f): [string, string, string | null] => [f.name, f.address, f.text]),
    ...Object.keys(typed).filter((a) => !node.fields.some((f) => f.address === a))
      .map((a): [string, string, string | null] => [a, a, null]),
  ];
  return (
    <div className="inspector">
      <h3>{node.label}</h3>
      <code className="address">{node.address}</code>
      {node.findings.map((f, i) => {
        const fix = f.next?.map(setCommand).find(Boolean);
        return (
          <div className={`finding ${f.severity}`} key={i}>
            <span className="message">{f.message}</span>
            {fix && <button className="quiet" onClick={() => setTyped({ ...typed, [fix.address]: fix.value })}>
              prepare the fix</button>}
          </div>
        );
      })}
      {rows.map(([name, address, text]) => {
        const current = typed[address] ?? text ?? "";
        return (
          <label key={address}>{name}
            <span className="field-row">
              <input value={current} spellCheck={false} onChange={(e) => setTyped({ ...typed, [address]: e.target.value })} />
              <button disabled={current === text} onClick={() => set(address, current)}>Set</button>
            </span></label>
        );
      })}
      <div className="actions">
        <button className="quiet" onClick={() => change({ operation: "model.unset", request: { project, address: node.address },
          title: `remove ${node.address}` })}>Remove</button>
        {node.renamable && (
          <span className="field-row">
            <input value={rename} placeholder="new name" onChange={(e) => setRename(e.target.value.trim())} />
            <button className="quiet" disabled={!rename} onClick={() => change({ operation: "model.rename",
              request: { project, address: node.address, name: rename }, title: `rename ${node.label} to ${rename}` })}>Rename</button>
          </span>)}
      </div>
    </div>
  );
}

export function ModelWorkspace({ project, study, onStudies, onNeedToken }: {
  project: string; study: string | null; onStudies: (s: string[]) => void; onNeedToken: () => void;
}) {
  const [graph, setGraph] = useState<Graph | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [entry, setEntry] = useState<Entry | null>(null);
  const [pending, setPending] = useState<Change | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const asked = useRef(0);                          // only the latest answer is drawn

  const failed = useCallback((e: unknown) => {
    if (e instanceof NeedToken) onNeedToken();
    else setError(String((e as Error)?.message || e));
  }, [onNeedToken]);
  const load = useCallback(() => {
    const ticket = ++asked.current;
    runOperation("model.graph", { project, ...(study ? { study } : {}) })
      .then(({ result }) => {
        if (ticket !== asked.current) return;
        setGraph(result); setError(null); onStudies(result.studies);
      })
      .catch((e) => { if (ticket === asked.current) failed(e); });
  }, [project, study, onStudies, failed]);
  // Another project or study: nothing of the last one stays — not its graph, its selection or its change.
  useEffect(() => { setGraph(null); setSelected(null); setEntry(null); setPending(null); setError(null); },
            [project, study]);
  useEffect(load, [load]);
  useEffect(() => {
    if (!graph) return;
    const rank = new Map(graph.nodes.map((n) => [n.address, n.rank]));
    setNodes(layout(graph.nodes));
    // Each wire drawn in the chain's order, from the earlier node to the later (api.md § 5.2.2),
    // whichever of the two holds the reference.
    setEdges(graph.edges.map((e) => {
      const [from, to] = (rank.get(e.source) ?? 0) <= (rank.get(e.target) ?? 0) ? [e.source, e.target] : [e.target, e.source];
      return { id: `${e.source}→${e.target}@${e.address}`, source: from, target: to, label: e.port,
               className: `edge-${e.type.split(":")[0]}`, data: { edge: e } };
    }));
  }, [graph]);

  const byAddress = useMemo(() => new Map((graph?.nodes ?? []).map((n) => [n.address, n])), [graph]);
  const node = selected ? byAddress.get(selected) ?? null : null;
  const findings = useMemo(() => [...(graph?.nodes.flatMap((n) => n.findings.map((f) => ({ f, at: n.address }))) ?? []),
    ...(graph?.issues ?? []).map((f) => ({ f, at: null as string | null }))], [graph]);

  const connect = (c: Connection) => {
    const wire = between(byAddress.get(c.source), byAddress.get(c.target));
    if (wire) setPending(wired(project, wire.port, wire.to));
  };
  // A deletion on the canvas is planned, never drawn first: the canvas shows the files (api.md § 5.2).
  const remove = async ({ nodes: gone, edges: cutting }: { nodes: Node[]; edges: Edge[] }) => {
    if (gone.length === 1) {
      setPending({ operation: "model.unset", request: { project, address: gone[0].id }, title: `remove ${gone[0].id}` });
    } else if (gone.length === 0 && cutting.length === 1) {
      const e = cutting[0].data!.edge as GraphEdge;
      const change = cut(project, byAddress.get(e.source), byAddress.get(e.target), e);
      if (typeof change === "string") setError(change); else setPending(change);
    } else {
      setError("remove one node or one wire at a time");
    }
    return false;
  };
  // A position is presentation, read by no other step (models.md § 11.2): planned and applied at
  // once, with the plan's digest.
  const moved = async (_: unknown, _n: Node, dragged: Node[]) => {
    const positions = Object.fromEntries(dragged.map((n) => [n.id, [Math.round(n.position.x), Math.round(n.position.y)]]));
    const request = { project, positions };
    try {
      const { digest } = await planOperation("model.layout", request);
      for await (const line of lines(await apply("model.layout", request, digest))) {
        if (line.refused || line.defect || line.ok === false) throw new Error(line.message ?? "the layout was not saved");
      }
    } catch (e) {
      if (e instanceof NeedToken) return onNeedToken();
      setError(`the position was not saved: ${String((e as Error)?.message || e)}`);
    }
  };

  if (error && !graph) return <div className="card result not-ok"><p>{error}</p></div>;
  if (!graph) return <p className="muted pad">Loading the model…</p>;
  const choose = (e: Entry) => { setEntry(e); setSelected(null); setPending(null); };
  return (
    <div className="model-workspace">
      <aside className="model-palette"><Palette graph={graph} choose={choose} /></aside>
      <section className="model-canvas">
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
          onNodeClick={(_, n) => { setSelected(n.id); setEntry(null); }} onPaneClick={() => { setSelected(null); setEntry(null); }}
          isValidConnection={(c) => !!between(byAddress.get(c.source), byAddress.get(c.target))}
          onConnect={connect} onBeforeDelete={remove} onNodeDragStop={moved} fitView proOptions={{ hideAttribution: true }}>
          <Background /><Controls /><MiniMap pannable zoomable />
        </ReactFlow>
      </section>
      <aside className="model-inspector">
        {pending ? <PlanApply key={JSON.stringify(pending)} change={pending} onCancel={() => setPending(null)}
                              onDone={() => { setPending(null); setEntry(null); load(); }} />
          : entry ? <AddForm key={entry.group + entry.kind} graph={graph} entry={entry} project={project} change={setPending} />
          : node ? <NodeForm key={node.address + JSON.stringify(node.fields)} node={node} project={project} change={setPending} />
          : <ModelForm graph={graph} project={project} change={setPending} />}
        {error && <p className="problems">{error}</p>}
      </aside>
      <section className="model-bottom">
        <div className="group-name">findings — {findings.length || "none"}</div>
        <ul className="findings">
          {findings.map(({ f, at }, i) => (
            <li key={i} className={`finding ${f.severity}`} onClick={() => { if (at) { setSelected(at); setEntry(null); } }}>
              <span className="severity">{f.subject}</span><span className="message">{f.message}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
