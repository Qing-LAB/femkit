import type { Issue } from "../generated/schemas";
import { ActionButton } from "./ActionButton";
import "./Finding.css";

// A finding (web.md § 9.2): its sentence, what it is about, and its next steps as buttons.

const MEANING: Record<string, string> = { error: "bad", warning: "warn", info: "info" };

export function Finding({ issue, quiet, onSelect }: { issue: Issue; quiet?: boolean; onSelect?: () => void }) {
  return (
    <div className={`finding finding--${MEANING[issue.severity] ?? "info"} ${quiet ? "finding--quiet" : ""}`}>
      <div className="finding__text">
        {issue.label && (onSelect
          ? <button type="button" className="finding__subject" onClick={onSelect}>{issue.label}</button>
          : <span className="finding__subject">{issue.label}</span>)}
        <span className="finding__message">{issue.message}</span>
      </div>
      {!quiet && (issue.next ?? []).filter((a) => a.call).length > 0 && (
        <div className="finding__next">
          {(issue.next ?? []).filter((a) => a.call).map((a, i) => <ActionButton key={i} action={a} small />)}
        </div>
      )}
    </div>
  );
}
