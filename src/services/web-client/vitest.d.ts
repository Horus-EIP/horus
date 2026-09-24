/// <reference types="vitest/globals" />

// Vitest runs with `globals: true` (see vitest.config.ts), so describe/it/expect/vi
// are available without importing them. This reference makes TypeScript aware of
// them, and the import below augments `expect` with @testing-library/jest-dom
// matchers (e.g. toBeInTheDocument) under Vitest. Types only — no runtime effect.
import "@testing-library/jest-dom/vitest";
