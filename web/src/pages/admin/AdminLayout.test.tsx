import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AdminLayout } from "@/pages/admin/AdminLayout";
import { useAuthStore } from "@/stores/authStore";

describe("AdminLayout top navigation", () => {
  afterEach(cleanup);

  beforeEach(() => {
    useAuthStore.setState({
      user: {
        userId: "admin-1",
        username: "support-admin",
        role: "admin",
        token: "test-token"
      },
      token: "test-token",
      isAuthenticated: true,
      isInitialized: true
    });
  });

  it("keeps the product navigation without advertising the source repository", () => {
    render(
      <MemoryRouter initialEntries={["/admin/traces"]}>
        <AdminLayout />
      </MemoryRouter>
    );

    expect(screen.getByRole("button", { name: "返回聊天" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "用户菜单" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "打开 GitHub 仓库" })).not.toBeInTheDocument();
    expect(screen.queryByText("Star")).not.toBeInTheDocument();
  });

  it("keeps navigation scrollable while the collapse control stays reachable in a short viewport", () => {
    const { container } = render(
      <MemoryRouter initialEntries={["/admin/traces"]}>
        <AdminLayout />
      </MemoryRouter>
    );

    const sidebarNavigation = container.querySelector(".admin-sidebar nav");
    expect(sidebarNavigation?.className).toContain("min-h-0");
    expect(sidebarNavigation?.className).toContain("overflow-y-auto");
    expect(container.querySelector(".admin-sidebar__footer")?.className).toContain("shrink-0");
  });

  it("allows the admin shell and knowledge search to shrink without clipping the whole page", () => {
    const { container } = render(
      <MemoryRouter initialEntries={["/admin/traces"]}>
        <AdminLayout />
      </MemoryRouter>
    );

    expect(container.querySelector(".admin-main")?.className).toContain("min-w-0");
    expect(container.querySelector(".admin-topbar-inner")?.className).toContain("min-w-0");
    expect(container.querySelector(".admin-topbar-search")?.className).toContain("min-w-0");
    expect(container.querySelector(".admin-topbar-search")?.parentElement?.className).toContain(
      "min-w-0"
    );
  });
});
