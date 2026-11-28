// A library's own styles, applied through the page's object model (web.md § 5: the page's policy
// applies no style element; "styles a script sets through the page's object model are allowed"):
// a diagram's styles, and the style element the text editor's library writes and rewrites as it goes.

const mirrored = new WeakMap<HTMLStyleElement, CSSStyleSheet>();

/** ``css`` applied to the page as a sheet of its own. */
export function adopt(css: string): CSSStyleSheet {
  const sheet = new CSSStyleSheet();
  sheet.replaceSync(css);
  document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
  return sheet;
}

/** What ``draw`` makes, each style element it adds to the page applied through the object model and
 *  kept in step with its text from then on. */
export function adopting<T>(draw: () => T): T {
  const before = new Set(document.head.querySelectorAll("style"));
  const made = draw();
  for (const tag of document.head.querySelectorAll("style")) {
    if (before.has(tag) || mirrored.has(tag)) continue;
    const sheet = adopt(tag.textContent ?? "");
    mirrored.set(tag, sheet);
    new MutationObserver(() => sheet.replaceSync(tag.textContent ?? "")).observe(tag, { childList: true, characterData: true, subtree: true });
  }
  return made;
}
