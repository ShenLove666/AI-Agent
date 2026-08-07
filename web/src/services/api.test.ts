import { describe, expect, it } from "vitest";

import { apiErrorMessage } from "./api";

describe("apiErrorMessage", () => {
  it("turns FastAPI validation details into render-safe text", () => {
    expect(
      apiErrorMessage([
        { type: "int_parsing", loc: ["path", "doc_id"], msg: "Input should be a valid integer" }
      ])
    ).toBe("path.doc_id: Input should be a valid integer");
  });
});
