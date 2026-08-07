import { StrictMode } from "react";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthBootstrap } from "@/components/auth/AuthBootstrap";
import { getCurrentUser } from "@/services/authService";
import { useAuthStore } from "@/stores/authStore";

vi.mock("@/services/authService", () => ({
  getCurrentUser: vi.fn(),
  login: vi.fn(),
  logout: vi.fn()
}));

const mockedGetCurrentUser = vi.mocked(getCurrentUser);

describe("AuthBootstrap", () => {
  beforeEach(() => {
    window.localStorage.setItem("ragent_token", "test-token");
    useAuthStore.setState({
      user: null,
      token: null,
      isAuthenticated: false,
      isInitialized: false
    });
  });

  afterEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
  });

  it("keeps protected content hidden until token validation finishes", async () => {
    let resolveCurrentUser: (value: { userId: string; role: string }) => void;
    mockedGetCurrentUser.mockImplementation(
      () => new Promise((resolve) => (resolveCurrentUser = resolve))
    );

    render(
      <StrictMode>
        <AuthBootstrap>
          <p>运营台内容</p>
        </AuthBootstrap>
      </StrictMode>
    );

    expect(screen.getByText("正在连接运营台")).toBeInTheDocument();
    expect(screen.queryByText("运营台内容")).not.toBeInTheDocument();
    expect(mockedGetCurrentUser).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveCurrentUser!({ userId: "1", role: "admin" });
    });

    expect(await screen.findByText("运营台内容")).toBeInTheDocument();
  });
});
