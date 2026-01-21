import '@testing-library/jest-dom';
import { vi } from 'vitest';

// Make vi available as jest for compatibility with existing tests
// @ts-expect-error - Jest compatibility layer
globalThis.jest = vi;
