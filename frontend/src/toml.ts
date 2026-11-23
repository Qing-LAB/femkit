// A finding's fix line, read for the edit it names (models.md § 11.1).

/** A fix line a finding names — `python -m femkit model set ADDRESS VALUE` — as its parts. */
export function setCommand(line: string): { address: string; value: string } | null {
  const words: string[] = [];
  const re = /'((?:[^']|'"'"')*)'|"((?:[^"\\]|\\.)*)"|(\S+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(line.split("   #")[0]))) words.push((m[1] ?? m[2] ?? m[3]).replace(/'"'"'/g, "'"));
  const at = words.indexOf("set");
  if (at < 0 || words[at - 1] !== "model" || words.length < at + 3) return null;
  return { address: words[at + 1], value: words[at + 2] };
}
