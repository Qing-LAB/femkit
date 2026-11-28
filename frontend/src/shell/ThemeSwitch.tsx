import type { Page } from "../generated/schemas";
import { choose, useTheme } from "../kernel/theme";
import { Icon } from "../elements/Icon";
import "./ThemeSwitch.css";

// The theme switch (web.md § 10.2): the declaration's choices — the system's first, the default, then
// each theme of theme.toml — as one radio group in the top bar; the choice remembered in this browser
// alone.

export function ThemeSwitch({ page }: { page: Page }) {
  const chosen = useTheme();
  return (
    <div className="theme" role="radiogroup" aria-label={page.controls.theme.label} title={page.controls.theme.help}>
      {page.themes.map((t) => (
        <button key={t.theme ?? ""} type="button" role="radio" aria-checked={chosen === (t.theme ?? null)}
                aria-label={t.title} title={t.title} className="theme__choice" onClick={() => choose(t.theme ?? null)}>
          <Icon name={t.icon} size="sm" />
        </button>
      ))}
    </div>
  );
}
