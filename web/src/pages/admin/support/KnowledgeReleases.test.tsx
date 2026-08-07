import {render,screen} from "@testing-library/react";
import {describe,expect,it,vi} from "vitest";
import {supportOperationsMocks} from "./operationsTestMocks";
vi.mock("@/services/supportService",()=>supportOperationsMocks);
import {SupportOperationsPage} from "./SupportOperationsPage";
describe("KnowledgeReleases",()=>it("shows immutable active release evidence",async()=>{render(<SupportOperationsPage view="knowledge"/>);expect(await screen.findByText("support-v1")).toBeInTheDocument();expect(screen.getByText("当前生效")).toBeInTheDocument();expect(screen.getByText(/1 份冻结文档/)).toBeInTheDocument()}));
