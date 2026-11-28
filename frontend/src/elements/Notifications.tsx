import { useControl } from "../kernel/declared";
import { dismiss, useNotes } from "../kernel/notify";
import { Button } from "./Button";
import { Sentence } from "./Sentence";
import "./Notifications.css";

// The one stack (web.md § 9.2): what applied; what failed.

export function Notifications() {
  const notes = useNotes();
  const close = useControl("close");
  return (
    <div className="notes" role="status" aria-live="polite">
      {notes.map((n) => (
        <div key={n.id} className={`notes__note notes__note--${n.tone}`}>
          <span className="notes__text">
            {n.title && <strong className="notes__title">{n.title}</strong>}
            <Sentence text={n.text} />
          </span>
          <Button bare small icon={close.icon} aria-label={close.label} onClick={() => dismiss(n.id)} />
        </div>
      ))}
    </div>
  );
}
