// The server's sentences (web.md § 9.1: "one renderer draws the server's sentences: a command in
// backticks as code"): a sentence split once, by that one rule, for every place that draws one.

export interface Piece { code: boolean; text: string }

/** ``text``'s pieces: its words as they are, each part between backticks code. */
export function pieces(text: string): Piece[] {
  return text.split("`").map((part, i) => ({ code: i % 2 === 1, text: part }));
}
