# Frontend — AI Meeting Translator & Memo Hub

Next.js 16 (App Router, `cacheComponents`), TypeScript strict, Tailwind v4. See the root
[README](../README.md) for setup.

```bash
npm ci
BACKEND_URL=http://localhost:8000 npm run dev   # proxy target for /api/v1 (server-side only)
npm run lint && npm run typecheck && npm test && npm run build
npx playwright test                              # E2E against a running stack
```

* `src/app/(main)/…` — screens; `src/components/ui` — accessible primitives; `src/lib/i18n` — UI strings
  (Vietnamese; add locales by satisfying the `Messages` type).
* The browser never calls the backend directly and never stores secrets (no localStorage/sessionStorage).
