# Merchant Operations Frontend Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a visible first release of the “云桥数码 AI 运营台” with reliable authentication bootstrapping, a branded responsive shell, a merchant-focused chat experience, and a readable operations dashboard.

**Architecture:** Preserve the existing React/Zustand/service boundaries and backend API contracts. Add behavior-level UI tests, make route modules lazy, centralize brand/design tokens, and refactor only the visible core pages required for the first release.

**Tech Stack:** React 18, TypeScript, Zustand, React Router 6, Tailwind/CSS variables, Vitest, React Testing Library, Vite.

## Global Constraints

- Product name is `云桥数码 AI 运营台`.
- Core colors are deep navy `#0B1220`, teal `#14B8A6`, and warning amber `#F59E0B`.
- Preserve all existing API URLs and response-field compatibility.
- Do not invent metrics when an API returns no data; render an actionable empty state.
- Heavy preview and admin route implementations must not be statically loaded by the common chat entry.
- Modify files only under `D:\Project\rag-project`.

---

### Task 1: Test harness, auth bootstrap, and route loading

**Files:**
- Modify: `web/package.json`
- Modify: `web/package-lock.json`
- Modify: `web/vite.config.ts`
- Create: `web/src/test/setup.ts`
- Create: `web/src/components/auth/AuthBootstrap.tsx`
- Create: `web/src/components/auth/AuthBootstrap.test.tsx`
- Modify: `web/src/stores/authStore.ts`
- Modify: `web/src/App.tsx`
- Modify: `web/src/router.tsx`

**Interfaces:**
- Produces: `AuthState.isInitialized: boolean` and `AuthBootstrap({children})`.
- Preserves: `login`, `logout`, `checkAuth`, `fetchCurrentUser`, and every route path.

- [ ] Add `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`, and `jsdom` as dev dependencies; configure Vitest `environment: "jsdom"` and `setupFiles: "./src/test/setup.ts"`.
- [ ] Write a failing test rendering `AuthBootstrap` with the real Zustand store: while `checkAuth` is unresolved, users see `正在连接运营台`; after it resolves, children become visible. The production break caught is rendering a protected route before token validation finishes.
- [ ] Run `npm test -- AuthBootstrap.test.tsx` and confirm RED because the component and initialization state do not exist.
- [ ] Add `isInitialized`, set it only when `checkAuth` finishes, and implement the accessible bootstrap screen. Ensure `checkAuth` deduplicates concurrent initialization rather than issuing duplicate `/me` calls under StrictMode.
- [ ] Wrap `RouterProvider` in `AuthBootstrap`; change route guards to wait for initialized authentication.
- [ ] Convert page imports in `router.tsx` to `React.lazy` route elements with a shared page suspense fallback. Keep `/`, `/login`, `/chat`, `/chat/:sessionId`, `/admin/*`, preview, and 404 behavior unchanged.
- [ ] Run the focused test, full Vitest suite, ESLint, and `npm run build`; confirm GREEN and that admin pages are emitted as separate chunks.
- [ ] Commit with `fix: stabilize frontend bootstrap and routing`.

### Task 2: Brand shell, login, and merchant chat experience

**Files:**
- Create: `web/src/config/brand.ts`
- Create: `web/src/components/brand/BrandMark.tsx`
- Modify: `web/src/pages/LoginPage.tsx`
- Create: `web/src/pages/LoginPage.test.tsx`
- Modify: `web/src/components/layout/MainLayout.tsx`
- Modify: `web/src/components/layout/Header.tsx`
- Modify: `web/src/components/layout/Sidebar.tsx`
- Modify: `web/src/components/chat/WelcomeScreen.tsx`
- Modify: `web/src/components/chat/ChatInput.tsx`
- Modify: `web/src/pages/ChatPage.tsx`
- Modify: `web/src/styles/globals.css`

**Interfaces:**
- Produces: `BRAND_NAME`, `BRAND_SHORT_NAME`, and `DEMO_CREDENTIALS` constants used by login and shell.
- Consumes: existing auth store and chat store actions without changing backend payloads.

- [ ] Write a failing login behavior test that renders the real login page with a memory router, clicks `填入演示账号`, and observes username `merchant-demo` plus password `MerchantDemo@2026`. Assert product heading `云桥数码 AI 运营台` and that the password remains type `password`. The production breaks caught are missing demo onboarding and exposing the password.
- [ ] Run `npm test -- LoginPage.test.tsx` and confirm RED because the branded heading and fill action do not exist.
- [ ] Add brand constants and a compact geometric `BrandMark`; redesign login with a navy value panel, focused form card, demo fill action, visible submitting state, and inline login error. Do not persist the demo password beyond the existing login action.
- [ ] Redesign the shell: fixed desktop navigation, mobile drawer, compact header context, visible user role, and accessible navigation labels. Replace old `Ragent` copy with brand constants.
- [ ] Replace generic welcome presets with merchant prompts tied to seeded data: quality-failure refund, seven-day-return boundary, and warranty repair. Show local model status (`V4 Flash`, `BGE 512d`) as descriptive badges without claiming a live health check.
- [ ] Make chat empty/loading/error states occupy the content viewport correctly; keep the composer reachable at 320px width and make the sources panel a full-width mobile overlay.
- [ ] Introduce CSS tokens for the three approved colors, typography, radii, focus rings, surfaces, and statuses. Remove only obsolete selectors encountered in the modified components; do not rewrite unrelated admin CSS.
- [ ] Run focused login/bootstrap tests, full Vitest, ESLint, and build; confirm responsive markup has no horizontal fixed widths below 640px.
- [ ] Commit with `feat: brand the merchant AI workspace`.

### Task 3: Operations dashboard, verification, and preview

**Files:**
- Modify: `web/src/pages/admin/dashboard/DashboardPage.tsx`
- Create: `web/src/pages/admin/dashboard/DashboardPage.test.tsx`
- Modify: `web/src/pages/admin/AdminLayout.tsx`
- Modify: `web/src/styles/globals.css`

**Interfaces:**
- Consumes: existing dashboard service response and admin authorization.
- Produces: KPI, trend, issue distribution, and action views that distinguish loading, error, empty, and populated data.

- [ ] Write a failing dashboard test with a complete fixture response: verify labeled KPI cards for `问题解决率`, `知识命中率`, `转人工率`, and `负反馈率`; write a second test where all series are empty and verify `暂无运营数据` plus a useful next action. The production breaks caught are unlabeled metrics and fake-looking zero dashboards.
- [ ] Run `npm test -- DashboardPage.test.tsx` and confirm RED on the new information hierarchy or empty state.
- [ ] Refactor the dashboard into small local presentational sections while keeping the existing data request. Use the approved token colors, explicit time range and freshness labels, and no random fallback values.
- [ ] Align `AdminLayout` navigation names with the agreed information architecture and make the active section obvious without relying on color alone.
- [ ] Run all frontend tests, ESLint, `npm run build`, and the repository API contract checker.
- [ ] Start the backend with `DB_URL=sqlite:///./data/ragent-v4-flash.db`, build the frontend once, and verify `/login`, `/chat`, and `/admin/dashboard` return successfully. Record the exact local URL for the user.
- [ ] Commit with `feat: refresh merchant operations dashboard` and push `main` after review.

