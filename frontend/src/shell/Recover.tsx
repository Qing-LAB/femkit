// A view the page could not draw says so and offers to read the page again, never a blank window
// (web.md § 9.1). Two causes are known: femkit rebuilt under an open page, so a piece of the old one
// is gone from the server — which `main.tsx` answers by reading the page again once — and a defect.

import { Component, type ReactNode } from "react";
import { useControl, useSaying } from "../kernel/declared";
import { Button } from "../elements/Button";
import "./Recover.css";

function Fallen({ error }: { error: Error }) {
  const redraw = useControl("redraw");
  return (
    <div className="recover" role="alert">
      <p className="recover__says">{useSaying("cannot-draw")}</p>
      <p className="recover__error">{error.message}</p>
      <Button icon={redraw.icon} title={redraw.help} onClick={() => window.location.reload()}>{redraw.label}</Button>
    </div>
  );
}

/** Holds what it wraps; where drawing it throws, says so instead of leaving the window blank. */
export class Recover extends Component<{ children: ReactNode }, { error?: Error }> {
  state: { error?: Error } = {};

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    return this.state.error ? <Fallen error={this.state.error} /> : this.props.children;
  }
}
