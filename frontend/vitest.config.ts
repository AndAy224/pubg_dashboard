import { defineConfig } from 'vitest/config'

/**
 * Kept separate from `vite.config.ts` so the dev/build config stays free of
 * test concerns — and so `tsconfig.node.json` can typecheck both.
 *
 * The environment is **node, not jsdom**. Nothing here renders a component:
 * this project's failure mode is silently wrong data, not wrong markup, and
 * every bug the frontend has actually shipped (typed-array alignment, a
 * mirrored heatmap transform, a dictionary miss blanking a row) lives in pure
 * functions that need no DOM. Adding jsdom would buy brittle render tests and
 * a large dependency for a class of bug this codebase does not have.
 */
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
    // The corpus tests below reach the local API and skip when it is absent;
    // a slow first response should not look like a failure.
    testTimeout: 20_000,
  },
})
