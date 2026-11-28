import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./generated/tokens.css";   // every design value, generated from theme.toml (web.md § 10.1): first
import "./styles/shell.css";
import { Shell } from "./shell/Shell";

// femkit rebuilt under an open page: a piece of the old page is gone from the server, and asking for it
// fails. The page reads itself again — once for this build of it, so a piece truly missing never
// reloads it over and over — and is never left blank (web.md § 9.1); a second failure is left to the
// shell, which says so (`Recover`).
const RELOADED = "femkit-reloaded-for";   // the build the page last read itself again for
window.addEventListener("vite:preloadError", (event) => {
  let done = false;
  try { done = sessionStorage.getItem(RELOADED) === import.meta.url; } catch { /* no storage: read the page again */ }
  if (done) return;
  event.preventDefault();
  try { sessionStorage.setItem(RELOADED, import.meta.url); } catch { /* reloading still helps */ }
  window.location.reload();
});

// One bundle, two pages: the workspaces at /, the document viewer at /docs (web.md §§ 2.2–2.3).
createRoot(document.getElementById("root")!).render(<StrictMode><Shell /></StrictMode>);
