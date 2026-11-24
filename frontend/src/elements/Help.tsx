import { useId, useState } from "react";
import type { Help as HelpPart } from "../generated/schemas";
import { viewerAddress } from "../kernel/client";
import "./Help.css";

// A help (web.md § 9.2): its sentence on hover and on keyboard focus, and `?` opening where it
// is defined in the document viewer. The sentence is the server's.

export function Help({ help }: { help?: HelpPart | null }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  if (!help) return null;
  const doc = help.doc;
  return (
    <span className="help" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <a className="help__mark" href={doc ? viewerAddress(doc.document, doc.anchor ?? undefined) : undefined} target="_blank"
         rel="noopener noreferrer" aria-describedby={id} tabIndex={0} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
         onClick={(e) => { if (!doc) e.preventDefault(); e.stopPropagation(); }}>?</a>
      <span id={id} role="tooltip" className={`help__tip ${open ? "help__tip--open" : ""}`}>
        {help.sentence}{doc && <span className="help__where"> — opens {doc.document.split("/").pop()}{doc.section ? ` § ${doc.section}` : ""}</span>}
      </span>
    </span>
  );
}
