import { dismiss, useNotes } from "../kernel/notify";
import { ActionButton } from "./ActionButton";
import "./Notifications.css";

// The one stack (web.md § 9.2): what applied, with its Undo; what failed.

export function Notifications() {
  const notes = useNotes();
  return (
    <div className="notes" role="status" aria-live="polite">
      {notes.map((n) => (
        <div key={n.id} className={`notes__note notes__note--${n.tone}`}>
          <span className="notes__text">{n.text}</span>
          {n.actions.map((a, i) => <ActionButton key={i} action={a} small tone="ghost" />)}
          <button type="button" className="notes__close" aria-label="dismiss" onClick={() => dismiss(n.id)}>×</button>
        </div>
      ))}
    </div>
  );
}
