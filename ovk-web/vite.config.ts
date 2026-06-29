import { defineConfig } from "vite";

// The Vite dev server is the dashboard host: a card grid linking each
// bundle's interactive .html, guide .md, and ground-truth .ts. Bundle .html
// files are zero-dep and also work opened directly from disk.
export default defineConfig({
  server: { port: 5173, open: true },
  publicDir: false,
  root: ".",
});
