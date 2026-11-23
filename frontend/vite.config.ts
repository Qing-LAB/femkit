import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The bundle is served by flask at /static/ (api.md § 5.1); `web build` ships dist/ (§ 5.3).
// No inline script or style may reach it (§ 5.5), so the module-preload polyfill, which is
// inlined, is off.
export default defineConfig({
  plugins: [react()],
  base: "/static/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    modulePreload: { polyfill: false },
    assetsInlineLimit: 0,
    sourcemap: false,
  },
});
