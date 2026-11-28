import { useEffect, useMemo, useRef, useState } from "react";
import type {
  ContextPart, Graph as GraphPart, Issue as IssuePart, Next as NextPart, OperationInfo, Shown, Workspace as WorkspacePart,
} from "../generated/schemas";
import bundle from "../generated/bundle.json";
import { actFor } from "../kernel/action";
import { contextsOf, useChoices } from "../kernel/choices";
import { useDeclared } from "../kernel/declared";
import { Read, requestFor, useDocument } from "../kernel/document";
import { useRuns } from "../kernel/runs";
import { go, openDrawer, SELECTED, useDrawer, usePage, WORKSPACE } from "../kernel/state";
import { measure } from "../kernel/tokens";
import { DefectShown, RefusalShown } from "../elements/ActionButton";
import { open } from "../kernel/flows";
import { useMarks } from "../kernel/marks";
import { Banner, WorkspaceTitle } from "../elements/Banner";
import { Button } from "../elements/Button";
import { Drawer } from "../elements/Drawer";
import { Empty } from "../elements/Empty";
import { Graph, related, type Sought } from "../elements/Graph";
import { Icon } from "../elements/Icon";
import { Inspector } from "../elements/Inspector";
import { Issue, Issues, OpenIssue } from "../elements/Issue";
import { Next } from "../elements/Next";
import { Parts } from "../elements/Parts";
import { Progress } from "../elements/Progress";
import { Report } from "../elements/Report";
import { Tabs } from "../elements/Tabs";
import { Chooser, ContextBar } from "../elements/Context";
import "./Workspace.css";

// A workspace showing a document (web.md §§ 2.2, 8.1, 9.3) — Project's `project graph`, Runs'
// `study flow`, any the declaration adds. The canvas is the workspace: it fills the height under one
// header row — the title, the document's summary, the next step, the context — and beside it one
// column of tabs: the selected node's inspector, taking the focus when a node is selected, then the
// panels the declaration gives — among them the master list of the graph's parts, which keeps the
// front when a node is found from it. Before its context is chosen, the hero and its first step, and the
// landing the declaration gives. It arranges elements; every word and part is the server's.

const INSPECTOR = "";      // the side column's tab of the selected node: no panel's key

function answerOf(read: Read | null): Shown | null {
  return read?.kind === "ok" ? read.value.result : null;
}

function Lost({ read }: { read: Read }) {
  if (read.kind === "refused") return <RefusalShown refusal={read.refusal} />;
  if (read.kind === "defect") return <DefectShown defect={read.defect} />;
  if (read.kind === "token" || read.kind === "unreachable" || read.kind === "unreadable") return <Empty title={bundle.gate.says[read.kind]} />;
  return null;
}

/** The first step offered before anything is shown: its operation as a form, in a dialog, the
 *  values ``given`` already filled — a template to copy. */
function First({ op, given = {}, children, card }: {
  op: OperationInfo; given?: Record<string, string>; children: React.ReactNode; card?: boolean;
}) {
  const state = usePage();
  const start = () => open(actFor(op, { ...requestFor(op, state).request, ...given }));
  return card ? <button type="button" className="workspace__card workspace__card--start" title={op.description}
                        onClick={start}>{children}</button>
              : <Button title={op.description} onClick={start}>{children}</Button>;
}

/** Under the hero (web.md § 10.2): a context's choices as cards, each choosing it, and the first step
 *  started from each choice of the request field the declaration names. */
function Landing({ workspace, op, part }: { workspace: WorkspacePart; op?: OperationInfo; part: ContextPart }) {
  const { page } = useDeclared();
  const state = usePage();
  const choices = useChoices(part, state);
  const landing = workspace.landing!;
  const starts = op && landing.starts ? op.choices[landing.starts] ?? [] : [];
  const verb = op?.words.join(" ");
  return (
    <div className="workspace__landing">
      <section className="workspace__cards" aria-label={part.label}>
        {(choices ?? []).map((c) => {
          const detail = landing.detail ? c.row[landing.detail] : undefined;
          return (
            <button key={c.value} type="button" className="workspace__card" title={part.help}
                    onClick={() => go({ [part.key]: c.value }, page.context)}>
              <span className="workspace__card-icon"><Icon name={workspace.icon} /></span>
              <span className="workspace__card-name">{c.label}</span>
              {Array.isArray(detail) && detail.length > 0 && (
                <span className="workspace__card-detail">{detail.map(String).join(" · ")}</span>
              )}
            </button>
          );
        })}
        {op && starts.map((s) => (
          <First key={s} op={op} given={{ [landing.starts!]: s }} card>
            <span className="workspace__card-icon"><Icon name={page.controls.add.icon} /></span>
            <span className="workspace__card-name">{verb}</span>
            <span className="workspace__card-detail">{s}</span>
          </First>
        ))}
      </section>
    </div>
  );
}

/** A panel the declaration gives the workspace: a read-only operation's document, or the runs
 *  going on, the page's own. */
function PanelBody({ read, shows = "report" }: { read: Read | null; shows?: string }) {
  const runs = useRuns();
  const says = useDeclared().page.says;
  if (read === null) {
    return runs.length ? <div className="workspace__runs">{runs.map((r) => <Progress key={r.address} {...r} />)}</div>
                       : <Empty title={says["none-yet"]} />;
  }
  const answer = answerOf(read);
  if (!answer) return read.kind === "waiting" ? <Empty title={says.loading} /> : <Lost read={read} />;
  if (shows === "issues") {      // its findings alone (web.md § 8.1, a panel's `shows`)
    return answer.issues?.length ? <div className="workspace__issues"><Issues issues={answer.issues} /></div>
                                 : <Empty title={says["none-yet"]} />;
  }
  return <Report report={answer.report} issues={answer.issues} />;
}

/** Whether a finding is the one a node carries: the same finding, by every field. */
function same(a: IssuePart, b: IssuePart): boolean {
  return a.code === b.code && a.subject === b.subject && a.file === b.file && a.line === b.line && a.message === b.message;
}

export function Workspace({ workspace }: { workspace: WorkspacePart }) {
  const { page, operations } = useDeclared();
  const state = usePage();
  const drawer = useDrawer();
  const op = workspace.document ? operations.get(workspace.document) : undefined;
  const read = useDocument(op, state, workspace.context);
  // Each panel's document — none for the page's own — the declaration's panels, fixed for a workspace.
  const reads = workspace.panels.map((p) => {
    const got = useDocument(p.document ? operations.get(p.document) : undefined, state, p.context);
    return p.document ? got : null;
  });
  const [tab, setTab] = useState(INSPECTOR);
  const [sought, setSought] = useState<Sought>();      // a node found from the list, its card brought into view
  const listing = useRef(false);                        // the selection is the list's: the list keeps the front
  const [narrow, setNarrow] = useState(false);
  const body = useRef<HTMLDivElement>(null);
  const parts = contextsOf(workspace.context, op?.request as never, page.context);

  // Narrow when the canvas and the side column no longer both have the least room they declare.
  useEffect(() => {
    if (!body.current) return;
    const least = measure("layout-canvas-min") + measure("layout-inspector-min");
    const seen = new ResizeObserver(([e]) => setNarrow(e.contentRect.width < least));
    seen.observe(body.current);
    return () => seen.disconnect();
  }, [read.kind]);

  const answer = answerOf(read);
  const blocks = answer?.report?.blocks ?? [];
  const graph = blocks.find((b): b is GraphPart => b.kind === "graph");
  const said = blocks.filter((b) => b.kind === "text" || b.kind === "code" || b.kind === "table");
  // The next step as the server gives it (web.md § 8.4): the parts' next steps where it offers them,
  // else its first finding — the server orders them, the first the next step.
  const next = [...blocks, ...reads.flatMap((r) => answerOf(r)?.report?.blocks ?? [])]
    .find((b): b is NextPart => b.kind === "next");
  const first = next ? undefined : [...(answer?.issues ?? []), ...reads.flatMap((r) => answerOf(r)?.issues ?? [])][0];
  const selected = graph?.nodes.find((n) => n.address === state[SELECTED]);
  // What the diagram marks: what the selection is related to, and what a plan shown is about — a save's
  // impact among them (web.md § 2.4).
  const impact = useMarks();
  const marked = useMemo(() => new Set([...(graph ? related(graph, state[SELECTED]) : []), ...impact.addresses]),
                         [graph, state[SELECTED], impact]);

  // A node selected brings its inspector to the front — unless it was found from the list, which stays;
  // one unselected leaves the first panel.
  useEffect(() => {
    if (listing.current) listing.current = false;
    else if (selected) setTab(INSPECTOR);
    else setTab((t) => (t === INSPECTOR ? workspace.panels[0]?.key ?? INSPECTOR : t));
  }, [state[SELECTED], !!selected]);

  const select = (address?: string) => {
    go({ [SELECTED]: address ?? "" });
    if (address && narrow) openDrawer("details");
  };
  // An address this graph does not draw is of a family another workspace draws, as the declaration says
  // which draws which (`families`): there it opens.
  const lead = (address: string) => {
    if (graph?.nodes.some((n) => n.address === address)) return select(address);
    const other = page.workspaces.find((w) => w.key !== workspace.key && w.families.some((f) => !workspace.families.includes(f)));
    if (other) go({ [WORKSPACE]: other.key, [SELECTED]: address });
  };
  // A node found from the list: selected, and its card brought into view.
  const find = (address: string) => {
    listing.current = address !== state[SELECTED];
    select(address);
    setSought((s) => ({ address, n: (s?.n ?? 0) + 1 }));
  };
  const openIssue = (issue: IssuePart) => {
    const node = graph?.nodes.find((n) => n.issues.some((i) => same(i, issue)));
    if (node) select(node.address);
  };

  if (read.kind === "incomplete") {
    const firstOp = workspace.first ? operations.get(workspace.first) : undefined;
    const missing = parts.filter((p) => (workspace.context as string[]).includes(p.key) && !state[p.key]);
    const cards = workspace.landing ? page.context.find((c) => c.key === workspace.landing!.cards) : undefined;
    if (firstOp || cards) {
      return (
        <div className="workspace workspace--landing">
          <Banner app={page.app} hero>
            {missing.map((p) => <Chooser key={p.key} part={p} hero />)}
            {firstOp && <First op={firstOp}>{firstOp.words.join(" ")}</First>}
          </Banner>
          <p className="workspace__empty">{workspace.empty}</p>
          {cards && <Landing workspace={workspace} op={firstOp} part={cards} />}
        </div>
      );
    }
    return (
      <div className="workspace">
        <WorkspaceTitle workspace={workspace}><ContextBar parts={parts} /></WorkspaceTitle>
        <Empty icon={workspace.icon} title={workspace.empty}><ContextBar parts={missing} /></Empty>
      </div>
    );
  }

  const details = page.controls.details, panelsControl = page.controls.panels;
  const inspector = selected && graph
    ? <Inspector key={selected.address} node={selected} graph={graph} lead={lead} />
    : <Empty icon={page.controls.select.icon ?? undefined} title={workspace.help} />;
  const tabs = [
    ...(selected ? [{ key: INSPECTOR, label: details.label, icon: details.icon, title: details.help }] : []),
    ...workspace.panels.map((p, i) => ({ key: p.key, label: p.title, title: p.help,
                                        count: answerOf(reads[i])?.issues?.length || undefined })),
  ];
  const shown = workspace.panels.findIndex((p) => p.key === tab);
  // A panel's body: the master list of the graph's parts, or its document's, or the runs going on.
  const panel = (i: number) => (workspace.panels[i]?.shows === "parts"
    ? graph ? <Parts graph={graph} selected={state[SELECTED]} find={find} /> : <Empty title={page.says.loading} />
    : <PanelBody read={reads[i] ?? null} shows={workspace.panels[i]?.shows} />);
  const side = shown >= 0 ? panel(shown) : inspector;

  return (
    <OpenIssue.Provider value={openIssue}>
      <div className={`workspace ${narrow ? "workspace--narrow" : ""}`}>
        <header className="workspace__head">
          <WorkspaceTitle workspace={workspace} />
          {said.length > 0 && <div className="workspace__said"><Report report={{ blocks: said }} /></div>}
          {(first || next) && (
            <div className="workspace__next">{first ? <Issue issue={first} compact /> : next && <Next block={next} inline />}</div>
          )}
          <ContextBar parts={parts} />
          {narrow && <Button small icon={details.icon} title={details.help} onClick={() => openDrawer("details")}>{details.label}</Button>}
          {narrow && workspace.panels.length > 0 && (
            <Button small icon={panelsControl.icon} title={panelsControl.help} onClick={() => openDrawer("panels")}>{panelsControl.label}</Button>
          )}
        </header>
        <div className="workspace__body" ref={body}>
          <div className="workspace__canvas">
            {graph ? <Graph graph={graph} selected={state[SELECTED]} marked={marked} select={select} sought={sought}
                            place={`${workspace.key} ${JSON.stringify(op ? requestFor(op, state).request : {})}`} />
                   : read.kind === "waiting" ? <Empty title={page.says.loading} /> : <div className="workspace__lost"><Lost read={read} /></div>}
          </div>
          {!narrow && (graph || workspace.panels.length > 0) && (
            <aside className="workspace__side">
              {tabs.length > 1 || workspace.panels.length > 0
                ? <Tabs quiet label={workspace.title} chosen={shown >= 0 ? tab : INSPECTOR} choose={setTab} tabs={tabs} />
                : null}
              <div className="workspace__panel">{side}</div>
            </aside>
          )}
        </div>
        {narrow && (
          <>
            <Drawer side="end" open={drawer === "details"} label={details.label} onClose={() => openDrawer(null)}>{inspector}</Drawer>
            <Drawer side="bottom" open={drawer === "panels"} label={panelsControl.label} onClose={() => openDrawer(null)}>
              <Tabs quiet label={workspace.title} chosen={shown >= 0 ? tab : workspace.panels[0]?.key ?? ""} choose={setTab}
                    tabs={tabs.filter((t) => t.key !== INSPECTOR)} />
              <div className="workspace__panel">{panel(shown >= 0 ? shown : 0)}</div>
            </Drawer>
          </>
        )}
      </div>
    </OpenIssue.Provider>
  );
}
