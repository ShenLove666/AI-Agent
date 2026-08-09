import {render,screen} from "@testing-library/react";
import {describe,expect,it,vi} from "vitest";
import {supportOperationsMocks} from "./operationsTestMocks";
vi.mock("@/services/supportService",()=>supportOperationsMocks);
import {SupportOperationsPage} from "./SupportOperationsPage";
vi.mock("@/stores/authStore", () => ({
  useAuthStore: (selector: (state: { user: { permissions: string[] } }) => unknown) =>
    selector({
      user: {
        permissions: [
          "knowledge.manage",
          "evaluation.read",
          "evaluation.run",
          "support.quality.read",
          "support.case.read"
        ]
      }
    })
}));

describe("EvaluationRuns",()=>it("renders deterministic scores and gate actions",async()=>{render(<SupportOperationsPage view="evaluation"/>);expect(await screen.findByText("门禁通过")).toBeInTheDocument();expect(screen.getByText(/14 用例/)).toBeInTheDocument();expect(screen.getByRole("button",{name:/批准上线/})).toBeInTheDocument()}));
