import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { DocsApp } from "./Docs";
import "./styles/tokens.css";   // the elements' values; the first page's own sheet follows it
import "./styles.css";

// One bundle, two pages: the operations at /, the document viewer at /docs (web.md § 2).
const viewer = window.location.pathname.startsWith("/docs");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {viewer ? <DocsApp /> : <App />}
  </StrictMode>,
);
