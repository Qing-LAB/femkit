import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import bundle from "./src/generated/bundle.json";

// The bundle is served by flask at the address the page declaration gives (web.md §§ 1, 8.1), written
// into the generated bundle file; `web build` ships dist/ (§ 3). No inline script or style may reach
// it (§ 5), so the module-preload polyfill, which is inlined, is off.
export default defineConfig({
  plugins: [react()],
  base: bundle.addresses.bundle,
  build: {
    outDir: "dist",
    emptyOutDir: true,
    modulePreload: { polyfill: false },
    assetsInlineLimit: 0,
    sourcemap: false,
  },
});
