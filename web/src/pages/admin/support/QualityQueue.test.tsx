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

describe("QualityQueue",()=>it("shows evidence-backed knowledge gaps",async()=>{render(<SupportOperationsPage view="quality"/>);expect(await screen.findByText("优惠券返还时效缺失")).toBeInTheDocument();expect(screen.getByText(/出现 4 次/)).toBeInTheDocument();expect(screen.getByRole("button",{name:"用当前版本解决"})).toBeInTheDocument()}));
