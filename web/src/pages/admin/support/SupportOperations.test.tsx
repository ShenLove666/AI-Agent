import {render,screen} from "@testing-library/react";
import {describe,expect,it,vi} from "vitest";
import {supportOperationsMocks} from "./operationsTestMocks";
vi.mock("@/services/supportService",()=>supportOperationsMocks);
import {SupportOperationsPage} from "./SupportOperationsPage";
describe("SupportOperations",()=>it("labels demo provenance and calculated metrics",async()=>{render(<SupportOperationsPage view="reports"/>);expect(await screen.findByText("当前为演示数据")).toBeInTheDocument();expect(screen.getByText("75%")).toBeInTheDocument();expect(screen.getByText(/不调用大模型编造指标/)).toBeInTheDocument()}));
