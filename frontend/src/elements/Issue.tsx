import { createContext, useContext } from "react";
import type { Issue as IssuePart } from "../generated/schemas";
import { said, useDeclared } from "../kernel/declared";
import { Actions } from "./ActionButton";
import { Icon } from "./Icon";
import { Sentence } from "./Sentence";
import "./Issue.css";

// An issue — a finding (web.md §§ 7.4, 9.2): its severity's icon and word, its sentence, where the
// person opens it — its file, line and key — what would be right, or the choices, and its next
// steps, each drawn as the action it is. A view that can lead from it to its node gives `OpenIssue`.

/** Where a view leads a finding when the person opens it — its node; none: it leads nowhere. */
export const OpenIssue = createContext<((issue: IssuePart) => void) | null>(null);

export function Issue({ issue, also = [], compact }: { issue: IssuePart; also?: IssuePart[]; compact?: boolean }) {
  const { page } = useDeclared();
  const look = page.severities[issue.severity];
  const open = useContext(OpenIssue);
  const where = (i: IssuePart) => [i.file && (i.line ? said(page.says.line, { file: i.file, line: i.line }) : i.file), i.key]
    .filter(Boolean).join(": ") || i.label || i.subject;
  const lead = (i: IssuePart) => (open ? <button type="button" className="issue__open" onClick={() => open(i)}>{where(i)}</button>
                                      : <span>{where(i)}</span>);
  return (
    <article className={`issue ${compact ? "issue--compact" : ""}`} data-severity={issue.severity}>
      <span className="issue__mark" title={look.label}><Icon name={look.icon} size="sm" label={look.label} /></span>
      <div className="issue__body">
        <p className="issue__message" title={compact ? issue.message : undefined}>
          {compact && open ? <button type="button" className="issue__open" onClick={() => open(issue)}><Sentence text={issue.message} /></button>
                           : <Sentence text={issue.message} />}
          {also.length > 0 && <span className="issue__count">{also.length + 1}</span>}
        </p>
        {also.length === 0 && !compact && <p className="issue__where">{lead(issue)}</p>}
        {also.length > 0 && !compact && (
          <details className="issue__each">
            <summary>{page.says.each}</summary>
            <ul>{[issue, ...also].map((i, n) => <li key={n} className="issue__where">{lead(i)}</li>)}</ul>
          </details>
        )}
        {!compact && issue.right !== null && <p className="issue__right"><code>{issue.right}</code></p>}
        {!compact && issue.choices.length > 0 && (
          <p className="issue__right">{issue.choices.map((c) => <code key={c}>{c}</code>)}</p>
        )}
        {!compact && issue.next.length > 0 && <Actions actions={issue.next} />}
      </div>
    </article>
  );
}

/** Every finding, in the order the server gives them — the first is the next step — those of one code
 *  and sentence as one, with their count and each one it is about on demand. */
export function Issues({ issues }: { issues: IssuePart[] }) {
  if (!issues.length) return null;
  const same = new Map<string, IssuePart[]>();
  for (const i of issues) {
    const key = `${i.severity}\u0000${i.code}\u0000${i.message}`;
    same.set(key, [...(same.get(key) ?? []), i]);
  }
  return (
    <div className="issue__list">
      {[...same.values()].map(([first, ...also], n) => <Issue key={n} issue={first} also={also} />)}
    </div>
  );
}
