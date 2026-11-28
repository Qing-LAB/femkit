import type { Fact as FactPart } from "../generated/schemas";
import { Badge } from "./Badge";
import "./Fact.css";

// What a person reads of a node, as its operation builds it (web.md § 7.6): its label and its
// value, a block word where it is a state's.

export function Fact({ fact }: { fact: FactPart }) {
  return (
    <div className="fact">
      <dt className="fact__label">{fact.label}</dt>
      <dd className="fact__value" data-shows={fact.shows ?? undefined}>
        {fact.shows ? <Badge toned>{fact.value}</Badge> : fact.value}
      </dd>
    </div>
  );
}
