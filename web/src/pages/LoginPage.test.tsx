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
  it("renders the login form with username and password fields", () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <LoginPage />
      </MemoryRouter>
    );

    expect(
      screen.getByRole("heading", { name: "邻里鲜选 AI 运营台" })
    ).toBeInTheDocument();
    expect(screen.getByLabelText("用户名")).toBeInTheDocument();
    expect(screen.getByLabelText("密码")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "登录运营台" })).toBeInTheDocument();
  });

  it("switches to register mode with confirm password field", async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <LoginPage />
      </MemoryRouter>
    );

    await user.click(screen.getAllByRole("button", { name: "注册商家账号" })[0]);

    expect(screen.getByLabelText("确认密码")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建账号并登录" })).toBeInTheDocument();

    // 切回登录
    await user.click(screen.getByRole("button", { name: "返回登录" }));
    expect(screen.queryByLabelText("确认密码")).not.toBeInTheDocument();
  });

  it("keeps the password input type as password by default", () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <LoginPage />
      </MemoryRouter>
    );

    expect(screen.getByLabelText("密码")).toHaveAttribute("type", "password");
  });
});
