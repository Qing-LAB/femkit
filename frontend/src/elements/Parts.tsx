import type { Graph as GraphPart, GraphNode } from "../generated/schemas";
import { useDeclared } from "../kernel/declared";
import { Badge } from "./Badge";
import { Count, scene, Swatch, worstOf } from "./Graph";
import "./Parts.css";

// The master list (web.md § 2.2): the project's parts beside the canvas, read from the canvas's own
// graph — the part kind the declaration lists (`canvas.listed`) at its head, then every node the
// canvas draws as a card, by its section in the layout's order, under Definitions each definition and
// each material — each in its category's shape, colour and icon, with its state, or its value, and its
// findings counted: its own and those of the objects its card shows as rows. A press selects the
// node and brings its card into view; the list changes nothing.

export function Parts({ graph, selected, find }: {
  graph: GraphPart; selected?: string; find: (address: string) => void;
}) {
  const { page } = useDeclared();
  const s = scene(graph, page.canvas);
  const entry = (n: GraphNode) => {
    const issues = [n, ...(s.objects.get(n.address) ?? [])].flatMap((x) => x.issues);
    return (
      <li key={n.address}>
        <button type="button" className="parts__entry" data-shows={n.shows ?? undefined}
                aria-current={n.address === selected || undefined} title={n.address} onClick={() => find(n.address)}>
          <Swatch section={n.section} stage={n.kind} />
          <span className="parts__name">{n.label}</span>
          {n.state ? <Badge toned={!!n.shows}>{n.state}</Badge>
                   : n.facts.map((f) => <span key={f.label} className="parts__value" title={f.label}>{f.value}</span>)}
          {issues.length > 0 && <Count count={issues.length} severity={worstOf(page.severities, issues)} />}
        </button>
      </li>
    );
  };
  const sections = Object.keys(page.sections).map((name) => ({ name, cards: s.cards.filter((c) => c.section === name) }))
    .filter((g) => g.cards.length > 0);
  return (
    <nav className="parts" aria-label={s.listed?.label}>
      {s.listed && <ul className="parts__list parts__list--head">{entry(s.listed)}</ul>}
      {sections.map((g) => (
        <section key={g.name} className="parts__section" aria-label={g.name}>
          <h3 className="parts__heading">{g.name}</h3>
          <ul className="parts__list">{g.cards.map(entry)}</ul>
        </section>
      ))}
    </nav>
  );
}
