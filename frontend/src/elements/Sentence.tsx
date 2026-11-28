import { Fragment } from "react";
import { pieces } from "../kernel/sentence";
import "./Sentence.css";

// A sentence the server wrote (web.md § 9.1: "one renderer draws the server's sentences: a command
// in backticks as code"): its words as they are, each part between backticks as code.

export function Sentence({ text }: { text: string }) {
  return (
    <>{pieces(text).map((p, i) => (p.code ? <code key={i} className="sentence__code">{p.text}</code>
                                          : <Fragment key={i}>{p.text}</Fragment>))}</>
  );
}
