import { describe, expect, it } from "vitest";

import { API_BASE_URL, api, apiErrorMessage } from "./api";

describe("API transport base URL", () => {
  it("uses the versioned API root for REST and streaming consumers", () => {
    expect(API_BASE_URL).toBe("/api/v1");
    expect(api.defaults.baseURL).toBe(API_BASE_URL);
  });
});

describe("apiErrorMessage", () => {
  it("turns FastAPI validation details into render-safe text", () => {
    expect(
      apiErrorMessage([
        { type: "int_parsing", loc: ["path", "doc_id"], msg: "Input should be a valid integer" }
      ])
    ).toBe("path.doc_id: Input should be a valid integer");
  });
});
