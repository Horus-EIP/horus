import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  globalIgnores([".next/**", "out/**", "build/**", "coverage/**", "next-env.d.ts"]),
  {
    files: ["hooks/use-web-socket.ts"],
    rules: {
      // Justification: useWebSocket synchronizes socket lifecycle state (connecting/disconnected) directly within useEffect.
      "react-hooks/set-state-in-effect": "off",
    },
  },
  {
    files: ["app/(protected)/knowledge-store/page.tsx"],
    rules: {
      // Justification: KnowledgeStorePage synchronizes localStorage upload queue and requested document modal directly within useEffect.
      "react-hooks/set-state-in-effect": "off",
    },
  },
]);

export default eslintConfig;
