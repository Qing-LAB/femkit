import { useRef, type KeyboardEvent } from "react";
import { Icon } from "./Icon";
import "./Tabs.css";

// One tab strip (web.md § 9.2): one tab stop, the arrow keys moving the choice.

export interface Tab { key: string; label: string; icon?: string; count?: number; title?: string }

export function Tabs({ tabs, chosen, choose, label }: { tabs: Tab[]; chosen: string; choose: (key: string) => void; label: string }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const move = (e: KeyboardEvent, i: number) => {
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const n = (i + step + tabs.length) % tabs.length;
    choose(tabs[n].key);
    refs.current[n]?.focus();
  };
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((t, i) => (
        <button key={t.key} ref={(el) => { refs.current[i] = el; }} type="button" role="tab" title={t.title}
                aria-selected={t.key === chosen} tabIndex={t.key === chosen ? 0 : -1} className="tabs__tab"
                onClick={() => choose(t.key)} onKeyDown={(e) => move(e, i)}>
          {t.icon && <Icon name={t.icon} size={15} />}<span>{t.label}</span>
          {t.count !== undefined && <span className="tabs__count">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}
