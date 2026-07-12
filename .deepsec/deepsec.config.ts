import { defineConfig } from "deepsec/config";

export default defineConfig({
  // This workspace authenticates via OPENROUTER_API_KEY (.env.local), not
  // AI_GATEWAY_API_KEY — "pi" is the only backend that can route through
  // OpenRouter. Model + --ai-api-key-env still have to be passed on the CLI
  // (deepsec.config.ts has no field for them); see package.json's
  // "process:openrouter" / "revalidate:openrouter" scripts.
  defaultAgent: "pi",
  projects: [
    { id: "fgrani-AE.CAP.AFA.1.1", root: ".." },
    // <deepsec:projects-insert-above>
  ],
});
