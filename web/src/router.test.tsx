import { render, waitFor } from "@testing-library/react";
import { RouterProvider } from "react-router-dom";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

const NativeRequest = globalThis.Request;
const NativeResizeObserver = globalThis.ResizeObserver;
const disposeAfterTest: Array<() => void> = [];

beforeAll(() => {
  // React Router only reads these fields. This avoids jsdom 29's AbortSignal
  // constructor differing from the one expected by Node's native Request.
  globalThis.Request = class RouterTestRequest {
    readonly url: string;
    readonly method: string;
    readonly signal: AbortSignal | null;
    readonly headers: Headers;

    constructor(input: RequestInfo | URL, init: RequestInit = {}) {
      this.url = String(input);
      this.method = init.method ?? "GET";
      this.signal = init.signal ?? null;
      this.headers = new Headers(init.headers);
    }
  } as typeof Request;
  globalThis.ResizeObserver = class RouterTestResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

afterAll(() => {
  globalThis.Request = NativeRequest;
  globalThis.ResizeObserver = NativeResizeObserver;
});

afterEach(() => {
  disposeAfterTest.splice(0).forEach((dispose) => dispose());
});

async function renderRoute(path: string, role: string) {
  window.history.replaceState({}, "", path);
  vi.resetModules();
  const [{ router }, { useAuthStore }, { api }] = await Promise.all([
    import("@/router"),
    import("@/stores/authStore"),
    import("@/services/api")
  ]);
  api.defaults.adapter = () => new Promise(() => {});
  useAuthStore.setState({
    user: { userId: `${role}-1`, username: role, role, token: "test-token" },
    token: "test-token",
    isAuthenticated: true,
    isInitialized: true
  });
  const view = render(<RouterProvider router={router} />);
  disposeAfterTest.push(() => {
    view.unmount();
    router.dispose();
  });
  return router;
}

describe("role-aware routing", () => {
  it("sends a signed-in supervisor from the home page to the supervisor queue", async () => {
    const router = await renderRoute("/", "supervisor");

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/admin/support-supervisor");
    });
  });

  it("sends a signed-in supervisor away from the login page to the supervisor queue", async () => {
    const router = await renderRoute("/login", "supervisor");

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/admin/support-supervisor");
    });
  });

  it.each(["/", "/login", "/admin"])(
    "keeps the admin default destination when entering through %s",
    async (path) => {
      const router = await renderRoute(path, "admin");

      await waitFor(() => {
        expect(router.state.location.pathname).toBe("/admin/support");
      });
    }
  );

  it.each(["/", "/login", "/admin"])(
    "sends a regular user entering through %s to chat",
    async (path) => {
      const router = await renderRoute(path, "user");

      await waitFor(() => {
        expect(router.state.location.pathname).toBe("/chat");
      });
    }
  );

  it.each([
    "/admin/support",
    "/admin/support-supervisor",
    "/admin/support-quality",
    "/admin/support-reports"
  ])("allows a supervisor to access %s", async (path) => {
    const router = await renderRoute(path, "supervisor");

    await waitFor(() => {
      expect(router.state.location.pathname).toBe(path);
    });
  });

  it.each([
    "/admin/support-knowledge",
    "/admin/support-evaluation",
    "/admin/retail",
    "/admin/dashboard",
    "/admin/operations",
    "/admin/knowledge",
    "/admin/knowledge/kb-1",
    "/admin/knowledge/kb-1/docs/doc-1",
    "/admin/traces",
    "/admin/traces/trace-1",
    "/admin/settings",
    "/admin/users"
  ])("prevents a supervisor from directly accessing %s", async (path) => {
    const router = await renderRoute(path, "supervisor");

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/admin/support-supervisor");
    });
  });

  it.each([
    "/admin/support",
    "/admin/support-supervisor",
    "/admin/support-knowledge",
    "/admin/support-quality",
    "/admin/support-evaluation",
    "/admin/support-reports",
    "/admin/retail",
    "/admin/dashboard",
    "/admin/operations",
    "/admin/knowledge",
    "/admin/traces",
    "/admin/settings",
    "/admin/users"
  ])("preserves admin access to %s", async (path) => {
    const router = await renderRoute(path, "admin");

    await waitFor(() => {
      expect(router.state.location.pathname).toBe(path);
    });
  });
});
