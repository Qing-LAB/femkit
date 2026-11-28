import type { Code as CodePart } from "../generated/schemas";
import "./Code.css";

// Text a person copies as it is (web.md § 7.7): a diagram's source, a file's lines.

export function Code({ block }: { block: CodePart }) {
  return <pre className="code">{block.text}</pre>;
}
