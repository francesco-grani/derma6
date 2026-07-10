// Vitest setup: registers jest-dom's DOM-focused matchers (toBeInTheDocument(),
// etc.) on Vitest's `expect`. Loaded automatically for every test file via
// `vite.config.ts`'s `test.setupFiles`.
import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

// Testing Library's auto-cleanup only self-registers when it detects a global
// `afterEach` (e.g. via Vitest's `test.globals: true`). This project keeps
// `globals` off and imports test APIs explicitly, so cleanup is registered
// here instead to unmount components between tests.
afterEach(() => {
  cleanup()
})
