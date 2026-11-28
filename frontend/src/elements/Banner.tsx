import type { ReactNode } from "react";
import type { App, Workspace } from "../generated/schemas";
import bundle from "../generated/bundle.json";
import { Icon } from "./Icon";
import "./Banner.css";

// The banner (web.md §§ 9.2, 10.2): the mark, the name and the tagline — the declaration's — as the
// hero over the accent's gradient before a project is open, its first step beneath, or folded into
// the top bar once one is; and a workspace's own title and tagline.

export function Banner({ app, hero, children }: { app: App; hero?: boolean; children?: ReactNode }) {
  if (!hero) {
    return (
      <a className="banner" href="#" title={app.tagline}>
        <img className="banner__mark" src={bundle.mark} alt={app.name} />
        <span className="banner__name">{app.name}</span>
      </a>
    );
  }
  return (
    <section className="banner banner--hero">
      <div className="banner__depth" aria-hidden="true">
        <img className="banner__echo" src={bundle.mark} alt="" />
      </div>
      <div className="banner__words">
        <img className="banner__mark banner__mark--hero" src={bundle.mark} alt="" />
        <div>
          <h1 className="banner__title">{app.name}</h1>
          <p className="banner__tagline">{app.tagline}</p>
        </div>
      </div>
      {children && <div className="banner__first">{children}</div>}
    </section>
  );
}

export function WorkspaceTitle({ workspace, children }: { workspace: Workspace; children?: ReactNode }) {
  return (
    <header className="banner__workspace">
      <span className="banner__workspace-mark"><Icon name={workspace.icon} /></span>
      <div className="banner__workspace-words">
        <h2 className="banner__workspace-title">{workspace.title}</h2>
        <p className="banner__workspace-tagline" title={workspace.help}>{workspace.tagline}</p>
      </div>
      {children && <div className="banner__workspace-aside">{children}</div>}
    </header>
  );
}
