import { defineConfig } from "vite";
import { readFileSync } from "node:fs";

export default defineConfig({
  envDir: false,
  plugins: [
    {
      name: "demo-prompts",
      resolveId(id) {
        if (id === "virtual:demo-prompts") return "\0demo-prompts";
      },
      load(id) {
        if (id !== "\0demo-prompts") return;
        const pack = JSON.parse(
          readFileSync(new URL("../pack/demo-scenarios.json", import.meta.url)),
        );
        const prompts = pack.order
          .map((id) => pack.scenarios.find((s) => s.id === id))
          .map((s) => ({
            id: s.id,
            title: s.title,
            question:
              s.question ??
              "What are the Sable daily limit and current Quartz location?",
          }));
        return `export default ${JSON.stringify(prompts)}`;
      },
    },
  ],
  build: { outDir: "dist", emptyOutDir: true },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{js,jsx}"],
    server: { deps: { inline: [/@openuidev\/react-ui/] } },
  },
});
