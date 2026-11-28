import { useMemo, useState } from "react";
import type { OperationInfo, Workspace as WorkspacePart } from "../generated/schemas";
import { actFor } from "../kernel/action";
import { useControl, useDeclared } from "../kernel/declared";
import { requestFor } from "../kernel/document";
import { go, OPERATION, usePage } from "../kernel/state";
import { Flow } from "../elements/ActionButton";
import { WorkspaceTitle } from "../elements/Banner";
import { Empty } from "../elements/Empty";
import { Icon } from "../elements/Icon";
import "./Operations.css";

// The Operations workspace (web.md § 2.1, operation view): every operation the page is served, as a
// form — banded by its group, in the declaration's order, each band its title, icon and accent — its
// plan, its progress and its outcome, all through the one action machine. It arranges elements.

/** One operation as a form (web.md § 2.1): its values to fill from the context and the server's fills,
 *  carried through the one action flow. */
function Form({ op }: { op: OperationInfo }) {
  const state = usePage();
  const act = useMemo(() => actFor(op, requestFor(op, state).request), [op, state]);
  return (
    <div className="operations__form" data-group={op.group}>
      <Flow key={op.name} act={act} inline head={(
        <header className="operations__head">
          <h3 className="operations__name">{op.words.join(" ")}</h3>
          <p className="operations__about">{op.description}</p>
          {Object.keys(act.request).length > 0 && (
            <p className="operations__given">{Object.entries(act.request).map(([k, v]) => <code key={k}>{k} = {String(v)}</code>)}</p>
          )}
        </header>
      )} />
    </div>
  );
}

export function Operations({ workspace }: { workspace: WorkspacePart }) {
  const { page, operations } = useDeclared();
  const state = usePage();
  const find = useControl("find");
  const [filter, setFilter] = useState("");
  const chosen = state[OPERATION] ? operations.get(state[OPERATION]) : undefined;
  const bands = Object.entries(page.groups).map(([key, group]) => ({
    key, group, ops: [...operations.values()].filter((o) => o.group === key
      && (!filter || `${o.name} ${o.description}`.toLowerCase().includes(filter.toLowerCase()))),
  })).filter((b) => b.ops.length);
  return (
    <div className="operations">
      <aside className="operations__list">
        <label className="operations__find">
          <Icon name={find.icon} size="sm" />
          <input type="search" placeholder={find.label} title={find.help} aria-label={find.label} value={filter}
                 onChange={(e) => setFilter(e.target.value)} />
        </label>
        <nav className="operations__bands">
          {bands.map(({ key, group, ops }) => (
            <section key={key} className="operations__band" data-group={key}>
              <h4 className="operations__band-title"><Icon name={group.icon} size="sm" />{group.title}</h4>
              {ops.map((o) => (
                <button key={o.name} type="button" title={o.description}
                        className={`operations__item ${o.name === chosen?.name ? "operations__item--chosen" : ""}`}
                        onClick={() => go({ [OPERATION]: o.name })}>
                  <span>{o.words.join(" ")}</span>
                  {o.effect !== "reads" && <span className={`operations__effect operations__effect--${o.effect}`} aria-label={o.effect} />}
                </button>
              ))}
            </section>
          ))}
        </nav>
      </aside>
      <main className="operations__main">
        <WorkspaceTitle workspace={workspace} />
        {chosen ? <Form key={chosen.name} op={chosen} /> : <Empty icon={workspace.icon} title={workspace.empty} />}
      </main>
    </div>
  );
}
