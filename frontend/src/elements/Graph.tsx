import {
  createContext, useContext, useEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent,
  type MouseEvent,
} from "react";
import {
  Background, BackgroundVariant, BaseEdge, Handle, MiniMap, Position, ReactFlow, ReactFlowProvider,
  getBezierPath, useNodesInitialized, useNodesState, useReactFlow, useUpdateNodeInternals, type Edge, type EdgeProps, type Node,
  type NodeProps, type Viewport, type XYPosition,
} from "@xyflow/react";
import ELK, { type ElkNode } from "elkjs/lib/elk-api.js";
import worker from "elkjs/lib/elk-worker.min.js?url";
import "@xyflow/react/dist/style.css";
import type { Graph as GraphPart, GraphNode, GraphPort, Wire } from "../generated/schemas";
import { carried, iconOf, said, sentence, useControl, useDeclared } from "../kernel/declared";
import { measure } from "../kernel/tokens";
import { Badge } from "./Badge";
import { Button } from "./Button";
import { Icon } from "./Icon";
import "./Graph.css";

// The canvas (web.md §§ 2.2, 2.4, 9.2): every diagram drawn from its `Graph` as free-standing cards —
// one for each part, or each stage, and a small one for each object of a type the declaration draws on
// its own (`canvas.cards`, the definitions) — and no frame, band or box round any, nor a card inside
// another. The part kind the declaration lists (`canvas.listed`, the project's master list) is no
// card, nor is any wire to or from it: the side column lists it (`Parts`). Every wire runs as the
// data says, from what is named to what names it — a study into the observables part that reads it.
// A card takes its group's colour, shape and icon, a part's section's or a stage's kind's, its state
// in its badge; a box the graph gives — a case, the stages cases share, a grouping folder — is a tag on
// the cards it holds. The person may put down copies of a card — the same node, its file one, kept in
// the page alone — and each wire runs between the cards of its ends that stand nearest each other;
// every card of a node lights together, each saying it is one of so many. Every named slot shows as a
// row: a part's or a stage's ports, then a part's objects, each a dot in the colour of what it carries,
// on the edge that faces the cards its wires come from or go to — the side most of them stand on, read
// again as cards move; where none is either side, inputs on the left and outputs on the right. A port
// whose names are no node of the graph — its types no kind of node the declaration knows, and nothing a
// wire carries — is no slot, as nothing ever reaches it: each name it holds is a chip on the card's kind
// line — a recipe's mesher — as a solve stage's engine is, where its node gives one. A card folds to
// its title, its wires reaching it there. Each wire is a smooth curve from
// slot to slot, coloured by what it carries, dashed where not checked yet; an input's triangle its direction.
// Where a card first stands is ELK's proposal (`elkjs`): the graph's columns in its sections' order,
// places alone. The person drags any card anywhere and the wires follow; a refresh, or coming back to
// the diagram while the page is open, keeps where it stands, ELK proposing only for cards the graph
// adds; Reset layout returns to ELK's proposal. Clicking a wire, selecting a card or a row, or
// reaching a card by the keyboard lights it, its wires and their ends, and dims the rest; the wires
// clicked are said in the declaration's sentences. The pointer passing over lights nothing (the
// person, 2026-11-27: highlight only what is clicked, as a card is). The canvas changes nothing: it selects.

/** What the canvas is given beside its graph: the node selected, those related to it, and how a
 *  node is selected — the view's, from the page state — and, where the view shows the graph as a
 *  document it reads again, that document's request: where the person's arrangement is kept. */
export interface Selecting {
  selected?: string;
  marked?: Set<string>;
  select?: (address?: string) => void;
  place?: string;
  sought?: Sought;
}

/** A node the person asked to find — from the list beside the canvas — and the how-many-th ask it is,
 *  so asking for the same node again brings its card into view again. */
export interface Sought { address: string; n: number }

const elk = new ELK({ workerUrl: worker });     // ELK in a worker of its own, a file the bundle ships
const IN = "in", OUT = "out";
const OF = "|";                                 // an object's slot: its address, then its side and port
const FACES = "#";                              // a slot of a card: the card, then the slot's handle

type Side = typeof IN | typeof OUT;
type Size = { width: number; height: number };
type Tone = "lit" | "dim" | undefined;

/** What the canvas reads of the project layout, as the declaration gives it. */
type Reading = { listed: string; cards: string[] };

/** The cards of a graph — its parts and stages, but the listed kind's, and each object of a type drawn
 *  on its own — and the objects each part shows as its rows, in the graph's order; the card an address
 *  is drawn on, none for what is listed and not drawn; the listed part itself. */
export interface Scene {
  cards: GraphNode[];
  objects: Map<string, GraphNode[]>;
  byAddress: Map<string, GraphNode>;
  cardOf: (address: string) => string | undefined;
  listed?: GraphNode;
}

export function scene(graph: GraphPart, reading: Reading): Scene {
  const byAddress = new Map(graph.nodes.map((n) => [n.address, n]));
  const alone = (n: GraphNode) => n.family === "object" && reading.cards.includes(n.kind);
  const listed = (n: GraphNode) => n.family === "part" && n.kind === reading.listed;
  const objects = new Map<string, GraphNode[]>();
  for (const n of graph.nodes) if (n.part && !alone(n)) objects.set(n.part, [...(objects.get(n.part) ?? []), n]);
  const cards = graph.nodes.filter((n) => (!n.part || alone(n)) && !listed(n));
  const drawn = new Set(cards.map((c) => c.address));
  const cardOf = (address: string) => {
    const n = byAddress.get(address), card = n && (alone(n) ? n.address : n.part ?? n.address);
    return card !== undefined && drawn.has(card) ? card : undefined;
  };
  return { cards, objects, byAddress, cardOf, listed: graph.nodes.find(listed) };
}

/** A wire as the canvas draws it: the cards it runs between, the slot of each it plugs into — the
 *  port it names, on its card or its object's row; the object's row itself; else the card's title —
 *  and the key of what it carries, its colour. */
interface Line {
  key: string;
  wire: Wire;
  source: string;
  target: string;
  sourceHandle: string;
  targetHandle: string;
  carries?: string;
}

function lines(s: Scene, wires: Wire[], folded: Set<string>, carriedBy: (type: string) => string | undefined): Line[] {
  const seen = new Map<string, number>();
  // A slot as drawn: a port the node declares on that side, or the card's title, or its object's row.
  const slot = (address: string, card: string, side: Side, port: string | null): string => {
    if (folded.has(card)) return side;
    const has = !!port && !!s.byAddress.get(address)?.ports.some((p) => p.name === port && p.side === side);
    if (address === card) return has ? `${side}:${port}` : side;
    return has ? `${address}${OF}${side}:${port}` : `${address}${OF}${side}`;
  };
  return wires.flatMap((w) => {
    const source = s.cardOf(w.source), target = s.cardOf(w.target);
    if (source === undefined || target === undefined || source === target) return [];
    const base = [w.source, w.source_port ?? "", w.target, w.target_port ?? "", w.address ?? ""].join(">");
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    const key = n ? `${base}>${n}` : base, carries = carriedBy(w.type);
    return [{ key, wire: w, source, target, carries,
              sourceHandle: slot(w.source, source, OUT, w.source_port), targetHandle: slot(w.target, target, IN, w.target_port) }];
  });
}

/** ELK's proposal of where each card first stands: a layered arrangement read left to right by the wires
 *  that run forward in the graph's reading order — what is named before what names it — so the cards a
 *  wire joins stand near each other and the whole fits in few columns; the cards' measured sizes,
 *  places alone. A section is told by its look, not its own column. */
function proposal(s: Scene, drawn: Line[], sizes: Map<string, Size>): ElkNode {
  const order = new Map(s.cards.map((c, i) => [c.address, i]));
  const forward = [...new Set(drawn.filter((l) => order.get(l.source)! < order.get(l.target)!)
    .map((l) => `${l.source}\n${l.target}`))].map((p) => p.split("\n"));
  return {
    id: "",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      "elk.spacing.nodeNode": String(measure("layout-graph-node-gap")),
      "elk.layered.spacing.nodeNodeBetweenLayers": String(measure("layout-graph-layer-gap")),
      "elk.layered.crossingMinimization.forceNodeModelOrder": "true",
      "elk.separateConnectedComponents": "false",
      "elk.padding": `[top=${measure("layout-graph-pad")},left=${measure("layout-graph-pad")}]`,
      // The columns stand from the top, in the graph's order, so the first view holds content.
      "elk.layered.nodePlacement.strategy": "INTERACTIVE",
    },
    children: s.cards.map((c) => ({ id: c.address, ...sizes.get(c.address) })),
    edges: forward.map(([a, b], i) => ({ id: `e${i}`, sources: [a], targets: [b] })),
  };
}

interface WireData extends Record<string, unknown> {
  carries?: string;
}

/** A wire: a smooth curve from slot to slot, in the colour of what it carries; the input's own
 *  triangle, inside its card, says which way it runs. */
function WireEdge({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, id }: EdgeProps<Edge<WireData>>) {
  const [path] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  return (
    <g data-wire={data?.carries}>
      <BaseEdge id={id} path={path} />
    </g>
  );
}

/** A slot as a row shows it: its handle, its side, what it carries, and whether it is lit. */
interface Slot { id: string; side: Side; carries?: string; lit: boolean }

/** One slot of a card, as a row: a port of the card's own; or a slot of an object inside it — a port of
 *  the object's, or the object itself where a wire reaches it whole — named by the object. Its words, its
 *  dot on its edge, the findings of the object it belongs to, and the object a press selects. */
interface Row {
  key: string;
  slots: Slot[];
  words?: string;
  title?: string;
  object?: GraphNode;
  count: number;
  severity?: string;
  selected: boolean;
  marked: boolean;
  lit: boolean;
}

interface CardData extends Record<string, unknown> {
  node: GraphNode;
  small: boolean;              // an object drawn on its own: its name, its value, its one slot
  shape?: string;              // its group's shape: a part's section's, a stage's kind's
  icon?: string;               // its group's icon
  copy: boolean;               // a copy the person put on the canvas, not the first card of its node
  copies: string;              // what each of its node's cards says when there are several; else nothing
  chips: string[];             // what its ports name that is no node — a recipe's mesher — as a stage's engine is
  count: number;
  severity?: string;
  tags: { label: string; tag: number }[];
  ends: Slot[];                // the title's own slots: the card named, or giving, whole
  rows: Row[];
  folded: boolean;
  selected: boolean;
  marked: boolean;
  tone: Tone;
  fold: (address: string) => void;
  duplicate: (id: string) => void;
  remove: (id: string) => void;
  select?: (address?: string) => void;
  focus: (address?: string) => void;
}

/** The worst severity among findings, in the order the declaration lists the severities. */
export function worstOf(severities: object, issues: { severity: string }[]): string | undefined {
  const order = Object.keys(severities);
  return issues.map((i) => i.severity).sort((a, b) => order.indexOf(a) - order.indexOf(b))[0];
}

/** How many findings, in the colour of the worst. */
export function Count({ count, severity }: { count: number; severity?: string }) {
  return <span className="graph__count" data-severity={severity}>{count}</span>;
}

/** A group's look in little — its shape, its colour and its icon — as the legend and the list beside
 *  the canvas show it: a section's, or a stage kind's. */
export function Swatch({ section, stage }: { section?: string | null; stage?: string }) {
  const { page } = useDeclared();
  const look = section ? page.sections[section] : stage ? page.stages[stage] : undefined;
  return (
    <span className="graph__swatch" data-shape={look?.shape} data-section={section ?? undefined}
          data-stage={section ? undefined : stage}><Icon name={look?.icon} size="xs" /></span>
  );
}

/** The edge each slot of each card faces, by the card's id and the slot's — `card#slot` — for the slots
 *  whose wires' other ends stand more on one side than the other; any other slot keeps its own side. */
const Facing = createContext(new Map<string, Position>());
const own = (slot: Slot) => (slot.side === IN ? Position.Left : Position.Right);

/** The dots of one row, or of a title, each on the edge it faces: where several stand on one edge, each
 *  after the first a step further in, so none hides another. */
function SlotDots({ slots, at }: { slots: Slot[]; at: (slot: Slot) => Position }) {
  const count = new Map<Position, number>();
  return slots.map((slot) => {
    const edge = at(slot), step = count.get(edge) ?? 0;
    count.set(edge, step + 1);
    return <Handle key={slot.id} id={slot.id} type={slot.side === IN ? "target" : "source"} isConnectable={false}
                   position={edge} data-wire={slot.carries} style={step ? { "--graph-slot-step": step } as CSSProperties : undefined}
                   className={`graph__slot ${slot.lit ? "graph__slot--lit" : ""}`} />;
  });
}

function CardRow({ row, at, select }: { row: Row; at: (slot: Slot) => Position; select?: (address?: string) => void }) {
  // A row whose every dot stands on the right edge reads from there.
  const right = row.slots.length > 0 && row.slots.every((s) => at(s) === Position.Right);
  const classes = ["graph__row", right && "graph__row--right", row.object && "graph__row--object",
                   row.selected && "graph__row--selected", row.marked && "graph__row--marked",
                   row.lit && "graph__row--lit"].filter(Boolean).join(" ");
  const press = row.object ? (e: MouseEvent) => { e.stopPropagation(); select?.(row.object!.address); } : undefined;
  return (
    <li className={classes} title={row.title} onClick={press}>
      <SlotDots slots={row.slots} at={at} />
      {row.object && <span className="graph__object">{row.object.label}</span>}
      {row.words && <span className="graph__words">{row.words}</span>}
      {row.count > 0 && <Count count={row.count} severity={row.severity} />}
    </li>
  );
}

function Card({ id, data }: NodeProps<Node<CardData>>) {
  const { node, small, shape, icon, copy, copies, chips, count, severity, tags, ends, rows, folded, selected, marked, tone,
          fold, duplicate, remove, select, focus } = data;
  const words = useControl(folded ? "open" : "fold"), twin = useControl("duplicate"), drop = useControl("remove-copy");
  // Each slot on the edge it faces; when one turns, React Flow measures the card's slots again, so its
  // wires reach them where they now stand.
  const facing = useContext(Facing), update = useUpdateNodeInternals();
  const at = (slot: Slot) => facing.get(`${id}${FACES}${slot.id}`) ?? own(slot);
  const turned = [...ends, ...rows.flatMap((r) => r.slots)].map(at).join(" ");
  useEffect(() => update(id), [id, turned]);
  const key = (e: KeyboardEvent) => {
    if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); select?.(node.address); }
  };
  const classes = ["graph__card", small && "graph__card--small", selected && "graph__card--selected", marked && "graph__card--marked",
                   tone && `graph__card--${tone}`].filter(Boolean).join(" ");
  const press = (act: (id: string) => void) => (e: MouseEvent) => { e.stopPropagation(); act(id); };
  return (
    <div className={classes} data-section={node.section ?? undefined} data-stage={node.section ? undefined : node.kind}
         data-shape={shape}
         data-shows={node.shows ?? undefined} role="button" tabIndex={0} aria-pressed={selected} aria-expanded={!folded}
         onKeyDown={key} onBlur={() => focus(undefined)}
         onFocus={(e) => { if (e.target === e.currentTarget && e.currentTarget.matches(":focus-visible")) focus(node.address); }}>
      <header className="graph__title">
        <SlotDots slots={ends} at={at} />
        <div className="graph__name-line">
          <span className="graph__icon"><Icon name={icon} size="sm" /></span>
          <span className="graph__name" title={node.label}>{node.label}</span>
          {count > 0 && <Count count={count} severity={severity} />}
          <span className="graph__controls nodrag">
            <Button bare small icon={twin.icon} aria-label={`${twin.label}: ${node.label}`} title={twin.help}
                    onClick={press(duplicate)} />
            {copy && <Button bare small icon={drop.icon} aria-label={`${drop.label}: ${node.label}`} title={drop.help}
                             onClick={press(remove)} />}
            {rows.length > 0 && (
              <Button bare small icon={words.icon} aria-label={`${words.label} ${node.label}`} title={words.help}
                      onClick={(e) => { e.stopPropagation(); fold(node.address); }} />
            )}
          </span>
        </div>
        {small ? (
          <div className="graph__kind-line">
            {node.facts.map((f) => <span key={f.label} className="graph__value" title={f.label}>{f.value}</span>)}
            {copies && <span className="graph__copies">{copies}</span>}
          </div>
        ) : (
          <div className="graph__kind-line">
            <span className="graph__kind">{node.type ? `${node.kind} · ${node.type}` : node.kind}</span>
            {node.state && <Badge toned={!!node.shows}>{node.state}</Badge>}
            {node.engine && <span className="graph__chip">{node.engine}</span>}
            {chips.map((c) => <span key={c} className="graph__chip">{c}</span>)}
            {tags.map((t) => <span key={t.label} className="graph__tag" data-tag={t.tag}>{t.label}</span>)}
            {copies && <span className="graph__copies">{copies}</span>}
          </div>
        )}
      </header>
      {!folded && rows.length > 0 && (
        <ul className="graph__rows">{rows.map((r) => <CardRow key={r.key} row={r} at={at} select={select} />)}</ul>
      )}
    </div>
  );
}

const TYPES = { card: Card };
const EDGES = { wire: WireEdge };

/** Why the canvas is laid out: its first graph, the person's reset, or the same graph read again. */
type Why = "first" | "reset" | "refresh";
type Laid = "measure" | "laying" | "placed";

/** Where the person left a diagram — the cards folded, the copies they put down, where each card stood,
 *  the view — kept while the page is open, by the document's request the view names (`place`), so
 *  coming back to it is the same graph read again; held in memory alone, never on the server or in a
 *  file. */
interface Left { folded: Set<string>; copies: Map<string, string[]>; held: Map<string, XYPosition>; viewport: Viewport }
const COPY = "~";               // a copy's card: its node's address, then its number
const left = new Map<string, Left>();

/** Each text a model holds — a list said as its items — for a sentence's placeholders. */
function texts(model: object): Record<string, string | undefined> {
  return Object.fromEntries(Object.entries(model).map(([k, v]) => [k,
    typeof v === "string" ? v : Array.isArray(v) && v.length && v.every((x) => typeof x === "string") ? v.join(", ") : undefined]));
}

function Canvas({ graph, selected, marked, select, place, sought }: { graph: GraphPart } & Selecting) {
  const { page } = useDeclared();
  const flow = useReactFlow();
  const controls = { fit: useControl("fit"), in: useControl("zoom-in"), out: useControl("zoom-out"),
                     reset: useControl("reset-layout"), twin: useControl("duplicate"), drop: useControl("remove-copy"),
                     legend: useControl("legend") };
  const [legend, setLegend] = useState(false);          // the legend, opened from the toolbar, over no card at first
  const [back] = useState(() => (place === undefined ? undefined : left.get(place)));   // where the person left it
  const [folded, setFolded] = useState<Set<string>>(back?.folded ?? new Set());
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [laid, setLaid] = useState<Laid>("measure");
  const [epoch, setEpoch] = useState(0);                 // each reset asks ELK for its proposal afresh
  const [picked, setPicked] = useState<string[]>([]);    // the wires clicked, by their keys: all under the click
  const [focused, setFocused] = useState<string>();     // the card the keyboard is on
  const [copies, setCopies] = useState<Map<string, string[]>>(back?.copies ?? new Map());   // each node's copies
  const [menu, setMenu] = useState<{ id: string; at: XYPosition; x: number; y: number }>();   // a card's own menu
  const numbered = useRef(0);
  // A card being dragged is React Flow's until it is dropped: no card is redrawn meanwhile, or the drag
  // would lose its way; what changed is drawn once it is dropped, and the card dropped stands on top.
  const dragging = useRef(false);
  const [dropped, setDropped] = useState(0);
  const raised = useRef(new Map<string, number>()), top = useRef(0);
  const initialized = useNodesInitialized();
  const run = useRef(0);     // each layout's number: one a newer graph began meanwhile is dropped
  const why = useRef<Why>(back ? "refresh" : "first");
  const last = useRef<{ epoch: number; graph?: GraphPart }>({ epoch: 0 });
  const held = useRef(back?.held ?? new Map<string, XYPosition>());   // where each card stands now
  const area = useRef<HTMLDivElement>(null);
  const tip = useRef<HTMLDivElement>(null);
  const restored = useRef(false);
  const fitting = useRef(false);                         // a fit waits on the placed cards' measures
  const [least, setLeast] = useState<number | undefined>(undefined);

  // The whole diagram in view, with the theme's padding — never drawn larger than it is, never so small
  // that its smallest words fall under the readable size: past that, it is drawn at that size, its
  // start in view, and the person pans.
  const fit = () => {
    const box = area.current?.getBoundingClientRect();
    const all = flow.getNodes();
    if (!box || !all.length) return;
    const drawn = flow.getNodesBounds(all.map((n) => n.id));
    if (!drawn.width || !drawn.height) return;
    const pad = measure("layout-graph-pad"), readable = measure("size-readable") / measure("type-size-2xs");
    const whole = Math.min((box.width - 2 * pad) / drawn.width, (box.height - 2 * pad) / drawn.height, 1);
    const zoom = Math.max(whole, readable);
    const x = zoom * drawn.width + 2 * pad <= box.width ? (box.width - zoom * drawn.width) / 2 : pad;
    const y = zoom * drawn.height + 2 * pad <= box.height ? (box.height - zoom * drawn.height) / 2 : pad;
    setLeast(Math.min(whole, zoom));
    void flow.setViewport({ x: x - zoom * drawn.x, y: y - zoom * drawn.y, zoom });
  };
  // On leaving, where the person left it: what is drawn, once placed.
  const now = useRef({ folded, nodes, laid, copies });
  now.current = { folded, nodes, laid, copies };
  useEffect(() => () => {
    const { folded: closed, nodes: drawn, laid: placed, copies: copied } = now.current;
    if (placed !== "placed" || place === undefined) return;
    left.set(place, { folded: closed, copies: copied, held: new Map(drawn.map((n) => [n.id, n.position])),
                      viewport: flow.getViewport() });
  }, []);

  const s = useMemo(() => scene(graph, page.canvas), [graph, page]);
  const carriedBy = (type: string) => carried(page, type);
  const drawn = useMemo(() => lines(s, graph.wires, folded, carriedBy), [s, graph, folded, page]);
  // Each node's cards: its first, and each copy the person put down — the same node, its file one.
  const instances = (address: string) => [address, ...(copies.get(address) ?? [])];
  const addressOf = (id: string) => (s.byAddress.has(id) ? id : id.slice(0, id.lastIndexOf(COPY)));
  // A copy of a card, where the person asks — by its menu, where they pressed; else beside the card.
  const duplicate = (id: string, at?: XYPosition) => {
    const address = addressOf(id), from = flow.getNode(id)?.position ?? { x: 0, y: 0 }, gap = measure("layout-graph-node-gap");
    const made = `${address}${COPY}${(numbered.current += 1)}`;
    held.current.set(made, at ?? { x: from.x + gap, y: from.y + gap });
    raised.current.set(made, (top.current += 1));
    setCopies((c) => new Map(c).set(address, [...(c.get(address) ?? []), made]));
    setMenu(undefined);
  };
  const remove = (id: string) => {
    const address = addressOf(id);
    held.current.delete(id);
    setCopies((c) => {
      const left = (c.get(address) ?? []).filter((x) => x !== id), n = new Map(c);
      if (left.length) n.set(address, left); else n.delete(address);
      return n;
    });
    setMenu(undefined);
  };
  const fold = (address: string) => setFolded((f) => {
    const n = new Set(f);
    if (n.has(address)) n.delete(address); else n.add(address);
    return n;
  });

  // The wires clicked, every one under the click — where curves cross or leave one slot together.
  const pickedLines = useMemo(() => drawn.filter((l) => picked.includes(l.key)), [picked, drawn]);

  // What is lit: the wires clicked and their ends; else the card the keyboard is on, or the
  // card or row selected, with what is related to it, its wires and their other ends. The rest is
  // dimmed while anything is lit.
  const lit = useMemo(() => {
    const wires = new Set<string>(), cards = new Set<string>(), slots = new Set<string>();
    const light = (l: Line) => {
      wires.add(l.key);
      cards.add(l.source).add(l.target);
      slots.add(`${l.source}${FACES}${l.sourceHandle}`).add(`${l.target}${FACES}${l.targetHandle}`);
    };
    if (pickedLines.length) {
      pickedLines.forEach(light);
      return { on: true, wires, cards, slots };
    }
    const at = focused ?? selected, card = at === undefined ? undefined : s.cardOf(at);
    if (at === undefined || card === undefined) return { on: false, wires, cards, slots };
    cards.add(card);
    marked?.forEach((m) => { const c = s.cardOf(m); if (c !== undefined) cards.add(c); });
    for (const l of drawn) {
      if (at === card ? l.source === at || l.target === at : l.wire.source === at || l.wire.target === at) light(l);
    }
    return { on: true, wires, cards, slots };
  }, [pickedLines, focused, selected, marked, drawn, s]);

  const worst = (issues: { severity: string }[]) => worstOf(page.severities, issues);

  // The slots each card's wires use, with what each carries: a whole one is drawn where a wire uses it.
  const used = useMemo(() => {
    const out = new Map<string, Map<string, string | undefined>>();
    const use = (card: string, handle: string, carries?: string) => {
      const m = out.get(card) ?? new Map<string, string | undefined>();
      if (!m.has(handle)) m.set(handle, carries);
      out.set(card, m);
    };
    for (const l of drawn) { use(l.source, l.sourceHandle, l.carries); use(l.target, l.targetHandle, l.carries); }
    return out;
  }, [drawn]);

  // A port in words: the first of the declaration's sentences it fills, the nodes it names said by
  // what a person calls them.
  const label = (address: string) => s.byAddress.get(address)?.label ?? address;
  const spoken = (p: GraphPort) => {
    const names = [...new Set(p.names.map(label))];
    return sentence(page.sentences.port, { ...texts(p), names: texts({ names }).names }) ?? p.name;
  };
  // A wire in words: the first of the declaration's sentences it fills — its source the node named or
  // giving, its target the part that names, or the node that takes.
  const say = (l: Line) => sentence(page.sentences.wire, {
    ...texts(l.wire), source: label(l.wire.source), target: label(s.cardOf(l.wire.target) ?? l.wire.target),
  });

  // A port whose names are no node of the graph: none of its types — each by its kind, before any place —
  // is a kind of node the declaration knows, nor anything a wire carries; no wire ever reaches it.
  const nodeless = (p: GraphPort) => p.accepts.length > 0 && p.accepts.every((type) =>
    !Object.values(page.kinds).some((kinds) => type.split(":")[0] in kinds) && carried(page, type) === undefined);

  const card = (n: GraphNode, id = n.address): Node<CardData> => {
    const mine = used.get(n.address) ?? new Map<string, string | undefined>();
    const slot = (id: string, side: Side, carries?: string): Slot =>
      ({ id, side, carries: mine.get(id) ?? carries, lit: lit.slots.has(`${n.address}${FACES}${id}`) });
    const whole = (id: string, side: Side) => (mine.has(id) ? [slot(id, side)] : []);
    // Its slots: its own ports; then each object of a part's that has one — a port of its own, or a wire
    // reaching it whole — named by the object, the object's findings counted there. An object with no
    // slot is read in the inspector, its findings counted on the card's title. A port's slot stands on
    // its own side.
    const portSlots = (p: GraphPort, id: (side: Side) => string): Slot[] =>
      [slot(id(p.side as Side), p.side as Side, carried(page, p.accepts[0] ?? ""))];
    const typed = (p: GraphPort) => `${p.name}: ${p.accepts.join(" | ")}`;
    const rows: Row[] = n.ports.filter((p) => !nodeless(p)).map((p) => {
      const slots = portSlots(p, (side) => `${side}:${p.name}`);
      return { key: `${p.side}:${p.name}`, slots, words: spoken(p), title: typed(p), count: 0, selected: false, marked: false,
               lit: slots.some((x) => x.lit) };
    });
    const unslotted: GraphNode[] = [];
    for (const o of s.objects.get(n.address) ?? []) {
      const ends = [...whole(`${o.address}${OF}${IN}`, IN), ...whole(`${o.address}${OF}${OUT}`, OUT)];
      const ports = o.ports.filter((p) => !nodeless(p)).map((p) => ({ p, id: `${o.address}${OF}${p.side}:${p.name}`,
                                          slots: portSlots(p, (side) => `${o.address}${OF}${side}:${p.name}`) }));
      if (!ends.length && !ports.length) { unslotted.push(o); continue; }
      const row = (key: string, slots: Slot[], first: boolean, p?: GraphPort): Row => ({
        key, slots, object: o, words: p ? spoken(p) : undefined, title: p ? typed(p) : undefined,
        count: first ? o.issues.length : 0, severity: first ? worst(o.issues) : undefined,
        selected: o.address === selected, marked: !!marked?.has(o.address),
        lit: slots.some((x) => x.lit) || o.address === (focused ?? selected),
      });
      if (!ports.length) rows.push(row(o.address, ends, true));
      ports.forEach(({ p, id, slots }, i) => rows.push(row(id, [...(i ? [] : ends), ...slots], i === 0, p)));
    }
    const closed = folded.has(n.address);
    const titled = [n, ...(closed ? s.objects.get(n.address) ?? [] : unslotted)].flatMap((x) => x.issues);
    const tag = (address: string) => graph.boxes.findIndex((b) => b.address === address) % page.tags.length;
    const group = n.section ? page.sections[n.section] : page.stages[n.kind], many = instances(n.address).length;
    return {
      id, type: "card", position: held.current.get(id) ?? { x: 0, y: 0 }, selectable: false, draggable: true,
      zIndex: raised.current.get(id),
      data: {
        node: n, small: n.family === "object", shape: group?.shape, icon: group?.icon ?? iconOf(page, n), copy: id !== n.address,
        copies: many > 1 ? said(page.says.copies, { count: many }) : "",
        chips: [...new Set([n, ...(s.objects.get(n.address) ?? [])].flatMap((x) => x.ports).filter(nodeless).flatMap((p) => p.names))],
        duplicate, remove, count: titled.length, severity: worst(titled),
        tags: graph.boxes.filter((b) => b.members.includes(n.address)).map((b) => ({ label: b.label, tag: tag(b.address) })),
        ends: [...whole(IN, IN), ...whole(OUT, OUT)], rows, folded: closed,
        selected: n.address === selected, marked: [n.address, ...(s.objects.get(n.address) ?? []).map((o) => o.address)]
          .some((a) => marked?.has(a)),
        tone: lit.on ? (lit.cards.has(n.address) ? "lit" : "dim") : undefined, fold, select, focus: setFocused,
      },
    };
  };

  // A new graph: read again with no card added, every card stays where it stands, its words updated in
  // place, and ELK proposes nothing; else each card is drawn unseen, so ELK is given its size.
  useEffect(() => {
    const before = last.current;
    const reason: Why = before.graph === undefined ? why.current : epoch !== before.epoch ? "reset" : "refresh";
    last.current = { graph, epoch };
    if (laid === "placed") held.current = new Map(nodes.map((n) => [n.id, n.position]));
    if (reason === "refresh" && laid === "placed" && s.cards.every((c) => held.current.has(c.address))) {
      setNodes(everyCard());
      return;
    }
    if (reason === "reset") {
      held.current.clear();
      setCopies(new Map());
    }
    why.current = reason;
    run.current += 1;
    setLaid("measure");
    setNodes(s.cards.map((c) => ({ ...card(c), className: "graph__unplaced" })));
  }, [s, epoch]);

  // Every card of every node in the graph — a node's first, then its copies — each where it stands.
  function everyCard(): Node[] {
    return s.cards.flatMap((c) => instances(c.address).filter((id) => held.current.has(id))
      .map((id) => ({ ...card(c, id), position: held.current.get(id)! })));
  }

  // Place, once every card is measured: a card already standing stays where it stands; ELK proposes
  // where each other one first stands.
  useEffect(() => {
    if (laid !== "measure" || !initialized) return;
    const sizes = new Map(nodes.map((n) => [n.id, { width: n.measured?.width ?? 0, height: n.measured?.height ?? 0 }]));
    if (sizes.size !== s.cards.length || [...sizes.values()].some((z) => !z.width || !z.height)) return;
    setLaid("laying");
    const mine = run.current, reason = why.current;
    const asked = proposal(s, drawn, sizes);
    void elk.layout(asked).catch(() => elk.layout({ ...asked, edges: [] })).then((root) => {
      if (mine !== run.current) return;
      const proposed = new Map((root.children ?? []).map((c) => [c.id, { x: c.x ?? 0, y: c.y ?? 0 }]));
      for (const c of s.cards) if (!held.current.has(c.address)) held.current.set(c.address, proposed.get(c.address)!);
      const placed = everyCard();
      held.current = new Map(placed.map((n) => [n.id, n.position]));
      setNodes(placed);
      setLaid("placed");
      if (reason !== "refresh") fitting.current = true;
      else if (back && !restored.current) {
        restored.current = true;
        void flow.setViewport(back.viewport);
      }
    });
  }, [laid, initialized, s, nodes]);

  // The whole in view once every card ELK placed is measured where it stands.
  useEffect(() => {
    if (laid !== "placed" || !fitting.current || !nodes.every((n) => n.measured?.width && n.measured?.height)) return;
    fitting.current = false;
    fit();
  }, [laid, nodes]);

  // A node the person asked to find: its card — the first of its copies, or the card it is a row of —
  // brought to the middle of the view, at the zoom the person left.
  useEffect(() => {
    const card = sought && laid === "placed" ? s.cardOf(sought.address) : undefined;
    const n = card === undefined ? undefined : flow.getNode(card);
    if (!n) return;
    void flow.setCenter(n.position.x + (n.measured?.width ?? 0) / 2, n.position.y + (n.measured?.height ?? 0) / 2,
                        { zoom: flow.getZoom(), duration: measure("motion-base") });
  }, [sought?.n]);

  // Selection, focus, hover, folds and marks move no card: each card's data, updated where it stands.
  useEffect(() => {
    if (laid !== "placed" || dragging.current) return;
    setNodes((now) => now.map((n) => ({ ...n, zIndex: raised.current.get(n.id),
                                        data: card(s.byAddress.get(addressOf(n.id))!, n.id).data })));
  }, [selected, marked, lit, folded, used, dropped]);

  // A copy put down or taken away: every card of every node, each where it stands.
  useEffect(() => {
    if (laid !== "placed") return;
    held.current = new Map([...held.current, ...nodes.map((n) => [n.id, n.position] as const)]);
    setNodes(everyCard());
  }, [copies]);

  // Each wire runs between the two cards of its ends that stand nearest each other — the gap between
  // the edges they turn to each other, and their middles' rise — chosen again as cards move, so a copy
  // put near what it joins takes its wires.
  const joined = useMemo(() => {
    const at = new Map<string, Line & { a: string; b: string }>();
    if (laid !== "placed") return at;
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const box = (id: string) => {
      const n = byId.get(id);
      return n && { x: n.position.x, y: n.position.y, w: n.measured?.width ?? 0, h: n.measured?.height ?? 0 };
    };
    const apart = (a: string, b: string) => {
      const p = box(a), q = box(b);
      if (!p || !q) return Infinity;
      const [l, r] = p.x + p.w / 2 <= q.x + q.w / 2 ? [p, q] : [q, p];
      return Math.hypot(r.x - (l.x + l.w), p.y + p.h / 2 - (q.y + q.h / 2));
    };
    for (const l of drawn) {
      let best = { a: l.source, b: l.target }, least = Infinity;
      for (const a of instances(l.source)) for (const b of instances(l.target)) {
        const d = apart(a, b);
        if (d < least) { least = d; best = { a, b }; }
      }
      at.set(l.key, { ...l, ...best });
    }
    return at;
  }, [drawn, laid, nodes, copies]);

  // The edge each slot faces: the side of its card most of its wires' other ends stand on, by their
  // middles; where as many stand on each side, or none beside it, the slot keeps its own side. A new
  // answer only when a slot turns, so a card is redrawn while dragged only then.
  const turns = useMemo(() => {
    const middle = new Map(nodes.map((n) => [n.id, n.position.x + (n.measured?.width ?? 0) / 2]));
    const votes = new Map<string, number>();
    const vote = (id: string, handle: string, other: string) => {
      const d = middle.get(other)! - middle.get(id)!, k = `${id}${FACES}${handle}`;
      if (d) votes.set(k, (votes.get(k) ?? 0) + Math.sign(d));
    };
    for (const { a, b, sourceHandle, targetHandle } of joined.values()) {
      if (!middle.has(a) || !middle.has(b)) continue;
      vote(a, sourceHandle, b);
      vote(b, targetHandle, a);
    }
    return JSON.stringify([...votes].filter(([, v]) => v).map(([k, v]) => [k, v > 0 ? Position.Right : Position.Left]).sort());
  }, [joined, nodes]);
  const facing = useMemo(() => new Map<string, Position>(JSON.parse(turns)), [turns]);

  const edges: Edge<WireData>[] = useMemo(() => {
    return [...joined.values()].map((l) => {
      const t = lit.on ? (lit.wires.has(l.key) ? "lit" : "dim") : undefined;
      return {
        id: l.key, source: l.a, target: l.b, sourceHandle: l.sourceHandle, targetHandle: l.targetHandle,
        type: "wire", focusable: false, ariaLabel: say(l), data: { carries: l.carries },
        className: ["graph__wire", !l.wire.checked && "graph__wire--waiting", t && `graph__wire--${t}`].filter(Boolean).join(" "),
      };
    });
  }, [joined, lit]);

  // A click on a wire picks every wire under it, a second click on the same ones lets them go; their
  // sentences stand by the click, in the canvas's own measure whatever the zoom, opening toward the
  // side of the canvas with the more room. The wires under it are those React Flow draws there, by id.
  const pick = (e: MouseEvent) => {
    const under = [...new Set(document.elementsFromPoint(e.clientX, e.clientY)
      .map((el) => el.closest(".react-flow__edge")?.getAttribute("data-id")).filter((id): id is string => !!id))];
    setPicked((was) => (was.join("\n") === under.join("\n") ? [] : under));
    const box = area.current?.getBoundingClientRect();
    if (!box || !tip.current) return;
    const x = e.clientX - box.left, y = e.clientY - box.top;
    tip.current.style.setProperty("--graph-tip-x", `${x}px`);
    tip.current.style.setProperty("--graph-tip-y", `${y}px`);
    tip.current.dataset.below = String(y < box.height / 2);
    tip.current.dataset.before = String(x > box.width / 2);
  };

  // The legend: each group the cards are told apart by — the sections, or the stage kinds — with its
  // shape, colour and icon; each kind the wires carry; and what a dashed wire means.
  const groups = [...new Set(s.cards.map((c) => c.section ?? c.kind))];
  const kinds = [...new Set(drawn.map((l) => l.carries).filter((k): k is string => !!k))];

  return (
    <div className={`graph graph--${laid}`}>
      <div className="graph__toolbar">
        <Button small bare icon={controls.legend.icon} aria-label={controls.legend.label} title={controls.legend.help}
                aria-expanded={legend} onClick={() => setLegend((o) => !o)} />
        <Button small bare icon={controls.reset.icon} aria-label={controls.reset.label} title={controls.reset.help}
                onClick={() => setEpoch((e) => e + 1)} />
        <Button small bare icon={controls.fit.icon} aria-label={controls.fit.label} title={controls.fit.help} onClick={fit} />
        <Button small bare icon={controls.in.icon} aria-label={controls.in.label} title={controls.in.help}
                onClick={() => void flow.zoomIn()} />
        <Button small bare icon={controls.out.icon} aria-label={controls.out.label} title={controls.out.help}
                onClick={() => void flow.zoomOut()} />
      </div>
      <div className="graph__area" ref={area}>
        <Facing.Provider value={facing}>
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={TYPES} edgeTypes={EDGES} onNodesChange={onNodesChange} minZoom={least}
                   onNodeClick={(_, n) => { setMenu(undefined); setPicked([]); select?.(addressOf(n.id)); }}
                   onPaneClick={() => { setMenu(undefined); setPicked([]); select?.(undefined); }}
                   onNodeDragStart={() => { dragging.current = true; setMenu(undefined); }}
                   onNodeDragStop={(_, n) => {
                     dragging.current = false;
                     raised.current.set(n.id, (top.current += 1));
                     setDropped((d) => d + 1);
                   }}
                   onNodeContextMenu={(e, n) => {
                     e.preventDefault();
                     const box = area.current?.getBoundingClientRect();
                     setMenu({ id: n.id, at: flow.screenToFlowPosition({ x: e.clientX, y: e.clientY }),
                               x: e.clientX - (box?.left ?? 0), y: e.clientY - (box?.top ?? 0) });
                   }}
                   onMoveStart={() => setMenu(undefined)}
                   onEdgeClick={(e) => { setMenu(undefined); pick(e); }}
                   nodesConnectable={false} nodesDraggable nodesFocusable={false} edgesFocusable={false}
                   elementsSelectable={false} deleteKeyCode={null} proOptions={{ hideAttribution: true }}>
          <Background variant={BackgroundVariant.Dots} gap={measure("space-5")} size={measure("size-rule")}
                      color="var(--color-dots)" className="graph__ground" />
          <MiniMap pannable zoomable className="graph__minimap" nodeClassName="graph__mini" />
        </ReactFlow>
        </Facing.Provider>
        {legend && (
          <div className="graph__legend" role="dialog" aria-label={controls.legend.label}
               onKeyDown={(e) => { if (e.key === "Escape") setLegend(false); }}>
            <span className="graph__legend-group">
              {groups.map((g) => (
                <span key={g} className="graph__legend-entry">
                  {s.cards.some((c) => c.section === g) ? <Swatch section={g} /> : <Swatch stage={g} />}{g}
                </span>
              ))}
            </span>
            {drawn.length > 0 && (
              <span className="graph__legend-group">
                {kinds.map((k) => (
                  <span key={k} className="graph__legend-entry"><span className="graph__legend-line" data-wire={k} />{k}</span>
                ))}
                <span className="graph__legend-entry">
                  <span className="graph__legend-line graph__legend-line--waiting" />{page.says["wire-unchecked"]}
                </span>
              </span>
            )}
          </div>
        )}
        <div ref={tip} className={`graph__tip ${pickedLines.length ? "graph__tip--shown" : ""}`} role="status">
          {pickedLines.map((l) => <p key={l.key} className="graph__tip-line">{say(l)}</p>)}
        </div>
        {menu && (
          <div className="graph__menu" role="menu" onKeyDown={(e) => { if (e.key === "Escape") setMenu(undefined); }}
               ref={(el) => { el?.style.setProperty("--graph-menu-x", `${menu.x}px`); el?.style.setProperty("--graph-menu-y", `${menu.y}px`); }}>
            <Button small bare icon={controls.twin.icon} title={controls.twin.help} role="menuitem" autoFocus
                    onClick={() => duplicate(menu.id, menu.at)}>{controls.twin.label}</Button>
            {menu.id !== addressOf(menu.id) && (
              <Button small bare icon={controls.drop.icon} title={controls.drop.help} role="menuitem"
                      onClick={() => remove(menu.id)}>{controls.drop.label}</Button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export function Graph({ graph, ...selecting }: { graph: GraphPart } & Selecting) {
  return <ReactFlowProvider><Canvas graph={graph} {...selecting} /></ReactFlowProvider>;
}

/** The nodes related to ``selected`` by the one relation between the diagrams (web.md § 2.4): a
 *  stage's `made_from`, both ways — what it is made from, and what is made from it. */
export function related(graph: GraphPart, selected?: string): Set<string> {
  const out = new Set<string>();
  if (!selected) return out;
  for (const n of graph.nodes) {
    if (n.address === selected) n.made_from.forEach((m) => out.add(m));
    if (n.made_from.includes(selected)) out.add(n.address);
  }
  return out;
}
