import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { KnowledgeListPage } from "@/pages/admin/knowledge/KnowledgeListPage";
import { getKnowledgeBasesPage } from "@/services/knowledgeService";

vi.mock("@/services/knowledgeService", () => ({
  deleteKnowledgeBase: vi.fn(),
  getKnowledgeBasesPage: vi.fn(),
  renameKnowledgeBase: vi.fn()
}));

describe("KnowledgeListPage empty state", () => {
  it("does not render an impossible 1 / 0 page position", async () => {
    vi.mocked(getKnowledgeBasesPage).mockResolvedValue({
      records: [],
      total: 0,
      current: 1,
      size: 10,
      pages: 0
    });

    render(
      <MemoryRouter>
        <KnowledgeListPage />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText("共 0 条")).toBeInTheDocument());
    expect(screen.queryByText("1 / 0")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "上一页" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "下一页" })).not.toBeInTheDocument();
  });
});
