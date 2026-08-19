import { defineConfig } from "vite";
import { copyFileSync, mkdirSync } from "fs";

export default defineConfig({
  server: { port: 5173, open: false },
  build: { target: "esnext", sourcemap: true },
  optimizeDeps: { include: ["genlayer-js", "viem"] },
  plugins: [
    {
      name: "copy-reviewer-files",
      closeBundle() {
        mkdirSync("dist/docs", { recursive: true });
        mkdirSync("dist/contracts", { recursive: true });
        copyFileSync("docs/CONSENSUS.md", "dist/docs/CONSENSUS.md");
        copyFileSync("docs/STATE.md", "dist/docs/STATE.md");
        copyFileSync("docs/PROJECT.md", "dist/docs/PROJECT.md");
        copyFileSync("contracts/source_quorum.py", "dist/contracts/source_quorum.py");
        copyFileSync("contracts/quorum_bond.py", "dist/contracts/quorum_bond.py");
      },
    },
  ],
});
