import type { ReactNode } from "react";
import type { App, Workspace } from "../generated/schemas";
import { Icon } from "./Icon";
import "./Banner.css";

// The banner (web.md § 9.2): the mark, the name and the tagline; and a workspace's own title and
// tagline beneath it. The words are the declaration's.

export function Banner({ app, children }: { app: App; children?: ReactNode }) {
  return (
    <header className="banner">
      <a className="banner__brand" href="#" title={app.tagline}>
        <img className="banner__mark" src={`/static/${app.mark}`} alt="" width={30} height={30} />
        <span className="banner__name">{app.name}</span>
      </a>
      {children}
    </header>
  );
}

export function WorkspaceTitle({ workspace, aside }: { workspace: Workspace; aside?: ReactNode }) {
  return (
    <div className="banner__workspace">
      <div className="banner__workspace-mark"><Icon name={workspace.icon} size={18} /></div>
      <div className="banner__workspace-words">
        <h1 className="banner__workspace-title">{workspace.title}</h1>
        <p className="banner__workspace-tagline" title={workspace.help}>{workspace.tagline}</p>
      </div>
      {aside && <div className="banner__workspace-aside">{aside}</div>}
    </div>
  );
}
