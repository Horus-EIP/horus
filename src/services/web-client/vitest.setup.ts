import '@testing-library/jest-dom';
import { vi } from 'vitest';

const lsStore: Record<string, string> = {};
Object.defineProperty(globalThis, 'localStorage', {
  value: {
    getItem: (k: string) => (k in lsStore ? lsStore[k] : null),
    setItem: (k: string, v: string) => {
      lsStore[k] = v;
    },
    removeItem: (k: string) => {
      delete lsStore[k];
    },
    clear: () => {
      Object.keys(lsStore).forEach((k) => delete lsStore[k]);
    },
  },
  configurable: true,
});

// Make vi available as jest for compatibility with existing tests
// @ts-expect-error - Jest compatibility layer
globalThis.jest = vi;
