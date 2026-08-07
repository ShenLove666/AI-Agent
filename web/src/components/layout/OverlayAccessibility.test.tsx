import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SourcesPanel } from "@/components/chat/SourcesPanel";
import { Sidebar } from "@/components/layout/Sidebar";
import { useAuthStore } from "@/stores/authStore";
import { useChatStore } from "@/stores/chatStore";

const initialAuthState = useAuthStore.getState();
const initialChatState = useChatStore.getState();

describe("closed workspace overlays", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockImplementation(() => ({
        matches: false,
        media: "(min-width: 1024px)",
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn()
      }))
    );
    useAuthStore.setState({
      ...initialAuthState,
      user: { userId: "merchant-demo", username: "merchant-demo", role: "merchant", token: "test" }
    });
    useChatStore.setState({
      ...initialChatState,
      sessions: [],
      sessionsLoaded: true,
      isLoading: false,
      openedSourceMessageId: null,
      fetchSessions: vi.fn().mockResolvedValue(undefined)
    });
  });

  afterEach(() => {
    useAuthStore.setState(initialAuthState, true);
    useChatStore.setState(initialChatState, true);
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("removes closed mobile navigation and sources controls from the tab order", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <button type="button">内容前</button>
        <Sidebar isOpen={false} onClose={() => undefined} />
        <SourcesPanel />
        <button type="button">内容后</button>
      </MemoryRouter>
    );

    const [navigation, sources] = container.querySelectorAll("aside");
    expect(navigation).toHaveAttribute("aria-hidden", "true");
    expect(navigation).toHaveAttribute("inert");
    expect(sources).toHaveAttribute("aria-hidden", "true");
    expect(sources).toHaveAttribute("inert");

    await user.tab();
    expect(screen.getByRole("button", { name: "内容前" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "内容后" })).toHaveFocus();
  });
});
