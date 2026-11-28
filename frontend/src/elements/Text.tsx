import type { Text as TextPart } from "../generated/schemas";
import { Sentence } from "./Sentence";
import "./Text.css";

// One line a person reads (web.md § 7.7).

export function Text({ block }: { block: TextPart }) {
  return <p className="text"><Sentence text={block.text} /></p>;
}
