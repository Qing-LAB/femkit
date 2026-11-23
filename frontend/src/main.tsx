import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { DocsApp } from "./Docs";
import "./styles.css";

// One bundle, two pages: the operations at /, the document viewer at /docs (api.md § 5.2).
const viewer = window.location.pathname.startsWith("/docs");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {viewer ? <DocsApp /> : <App />}
  </StrictMode>,
);
