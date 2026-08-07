import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { LoginPage } from "@/pages/LoginPage";

beforeAll(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class ResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  );
});

describe("LoginPage", () => {
  it("fills the merchant demo credentials without exposing the password", async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <LoginPage />
      </MemoryRouter>
    );

    expect(
      screen.getByRole("heading", { name: "云桥数码 AI 运营台" })
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "填入演示账号" }));

    expect(screen.getByLabelText("用户名")).toHaveValue("merchant-demo");
    expect(screen.getByLabelText("密码")).toHaveValue("MerchantDemo@2026");
    expect(screen.getByLabelText("密码")).toHaveAttribute("type", "password");
  });
});
