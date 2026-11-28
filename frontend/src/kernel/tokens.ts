// A design value read by its token's name (web.md § 10.1): the one way the page's code reaches a
// value of the theme — a measure the diagram's layout is given, how long a notice stays. Every value
// lives in theme.toml, written into tokens.css; the code holds none of its own.

function style(): CSSStyleDeclaration {
  return getComputedStyle(document.documentElement);
}

/** The token ``name`` — `layout-graph-node-gap`, `motion-linger` — as its custom property holds it. */
export function token(name: string): string {
  return style().getPropertyValue(`--${name}`).trim();
}

// CSS's own units, as a browser may give a token back — a time written `6000ms` read as `6s`.
const IN_PX_OR_MS: Record<string, number> = { "": 1, px: 1, ms: 1, s: 1000 };

/** The token ``name`` as a number: a length in px, a time in ms, as theme.toml writes it. */
export function measure(name: string): number {
  const [, value = "", unit = ""] = /^(-?[\d.]+)([a-z]*)$/.exec(token(name)) ?? [];
  return parseFloat(value) * (IN_PX_OR_MS[unit] ?? NaN);
}
