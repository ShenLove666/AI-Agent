import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./api";
import { listMessages } from "./sessionService";

describe("listMessages", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("prefers normalized sources when loading persisted chat history", async () => {
    vi.spyOn(api, "get").mockResolvedValue([
      {
        id: "assistant-1",
        role: "assistant",
        content: "牛肉搭配建议",
        citations: JSON.stringify([
          {
            id: "association:7",
            source: "commerce_association_rules",
            content: "牛肉与根茎类蔬菜共同出现 171 次",
            metadata: { provenance: "derived" }
          }
        ]),
        sources: [
          {
            index: 1,
            docId: "association:7",
            docName: "购物篮关联规则",
            sourceType: "internal_data",
            excerpt: "牛肉与根茎类蔬菜共同出现 171 次",
            provenance: "derived"
          }
        ]
      }
    ]);

    const messages = await listMessages("conversation-1");

    expect(messages[0].sources).toEqual([
      expect.objectContaining({
        docName: "购物篮关联规则",
        sourceType: "internal_data",
        provenance: "derived"
      })
    ]);
  });
});
