import { useEffect, useMemo, useState, type DragEvent } from "react";
import {
  Background, BackgroundVariant, Connection, Controls, Edge, Handle, MiniMap, Node, NodeProps, Position, ReactFlow,
  ReactFlowProvider, useEdgesState, useNodesState, useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Action, GraphEdge, GraphNode, GraphPort } from "../generated/schemas";
import type { Given } from "../kernel/action";
import { Icon } from "./Icon";
import "./Graph.css";

// The canvas (web.md § 9.2): a node from a graph node — its kind's icon, its place in the chain
// as its colour, a handle for each port — and each reference a wire, drawn in the chain's order.
// A port takes only what it accepts; every change is the document's own action, handed back to
// the view to carry through.

export interface GraphProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selected?: string;
  iconOf: (kind: string) => string;
  select: (address?: string) => void;
  act: (action: Action, given?: Given) => void;
  drop?: (payload: string, onto: GraphNode | undefined, at: { x: number; y: number }) => void;
  dropType?: string;
}

const takes = (p: GraphPort, n: GraphNode) => p.accepts.includes(n.kind) || p.accepts.includes(`${n.kind}:${n.type}`);
const COLUMN = 260, ROW = 104;

function Card({ data, selected }: NodeProps) {
  const { node, icon } = data as { node: GraphNode; icon: string };
  const wrong = (node.findings ?? []).length;
  return (
    <div className={`graph__node graph__node--rank-${node.rank} ${selected ? "graph__node--chosen" : ""} ${wrong ? "graph__node--wrong" : ""}`}>
      <Handle type="target" position={Position.Left} className="graph__in" />
      <div className="graph__kind"><Icon name={icon} size={13} /><span>{node.type ? `${node.kind} · ${node.type}` : node.kind}</span></div>
      <div className="graph__label">{node.label}</div>
      {wrong > 0 && <div className="graph__findings" title={(node.findings ?? []).map((f) => f.message).join("\n")}>{wrong} to resolve</div>}
      {(node.ports ?? []).map((p, i) => (
        <Handle key={p.name} id={p.name} type="source" position={Position.Right} className="graph__port"
                style={{ top: `${((i + 1) / ((node.ports ?? []).length + 1)) * 100}%` }} title={`${p.name}: ${p.accepts.join(" or ")}`} />
      ))}
    </div>
  );
}
const kinds = { fem: Card };

function Canvas({ nodes, edges, selected, iconOf, select, act, drop, dropType }: GraphProps) {
  const byAddress = useMemo(() => new Map(nodes.map((n) => [n.address, n])), [nodes]);
  const [drawn, setDrawn, onNodesChange] = useNodesState<Node>([]);
  const [wires, setWires, onEdgesChange] = useEdgesState<Edge>([]);
  const { screenToFlowPosition, fitView } = useReactFlow();
  const [fitted, setFitted] = useState(false);
  useEffect(() => {
    const rows: Record<number, number> = {};
    setDrawn(nodes.map((n) => {
      const row = (rows[n.rank] = (rows[n.rank] ?? -1) + 1);
      const position = { x: n.rank * COLUMN, y: row * ROW };   // in the chain's order; arranged in step G
      return { id: n.address, type: "fem", position, selected: n.address === selected, data: { node: n, icon: iconOf(n.kind) } };
    }));
    setWires(edges.map((e) => {
      const forward = (byAddress.get(e.source)?.rank ?? 0) <= (byAddress.get(e.target)?.rank ?? 0);
      return { id: `${e.source}→${e.target}@${e.address}`, source: forward ? e.source : e.target, target: forward ? e.target : e.source,
               label: e.port ?? "", className: `graph__wire graph__wire--${e.held}`, data: { edge: e } };
    }));
  }, [nodes, edges, selected, iconOf, byAddress, setDrawn, setWires]);
  useEffect(() => {
    if (!fitted && nodes.length) { requestAnimationFrame(() => fitView({ padding: 0.2, maxZoom: 1 })); setFitted(true); }
  }, [nodes, fitted, fitView]);

  const port = (c: Connection | Edge): { port: GraphPort; to: GraphNode } | null => {
    const from = byAddress.get(c.source), to = byAddress.get(c.target);
    const p = from?.ports?.find((x) => x.name === c.sourceHandle);
    return p && to?.name && takes(p, to) ? { port: p, to } : null;
  };
  return (
    <div className="graph" onDragOver={(e: DragEvent) => {
      if (dropType && e.dataTransfer.types.includes(dropType)) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; }
    }} onDrop={(e: DragEvent) => {
      if (!drop || !dropType || !e.dataTransfer.types.includes(dropType)) return;
      e.preventDefault();
      const id = (e.target as HTMLElement).closest(".react-flow__node")?.getAttribute("data-id");
      drop(e.dataTransfer.getData(dropType), id ? byAddress.get(id) : undefined, screenToFlowPosition({ x: e.clientX, y: e.clientY }));
    }}>
      <ReactFlow nodes={drawn} edges={wires} nodeTypes={kinds} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
        onNodeClick={(_, n) => select(n.id)} onPaneClick={() => select(undefined)}
        isValidConnection={(c) => !!port(c)}
        onConnect={(c) => { const w = port(c); if (w) act(w.port.connect, { name: w.to.name! }); }}
        onBeforeDelete={async ({ nodes: gone, edges: cut }) => {
          if (gone.length === 1) act(byAddress.get(gone[0].id)!.remove);
          else if (!gone.length && cut.length === 1) {
            const e = (cut[0].data as { edge: GraphEdge }).edge;
            if (e.cut) act(e.cut);
          }
          return false;   // the canvas shows the files: what is removed goes through its action
        }}
        proOptions={{ hideAttribution: true }} minZoom={0.3} maxZoom={1.6}>
        <Background variant={BackgroundVariant.Dots} gap={20} size={1.2} className="graph__ground" />
        <Controls showInteractive={false} className="graph__controls" />
        <MiniMap pannable zoomable className="graph__map" nodeClassName={(n) => `graph__map-node--rank-${(n.data as { node: GraphNode }).node.rank}`} />
      </ReactFlow>
    </div>
  );
}

export function Graph(props: GraphProps) {
  return <ReactFlowProvider><Canvas {...props} /></ReactFlowProvider>;
}
