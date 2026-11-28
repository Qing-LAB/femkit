import type { Next as NextPart } from "../generated/schemas";
import { Actions } from "./ActionButton";
import "./Next.css";

// A heading and the actions under it: what a person may do next (web.md § 7.7).

export function Next({ block, inline }: { block: NextPart; inline?: boolean }) {
  return (
    <section className={`next ${inline ? "next--inline" : ""}`}>
      <h4 className="next__label">{block.label}</h4>
      <Actions actions={block.actions} />
    </section>
  );
}
