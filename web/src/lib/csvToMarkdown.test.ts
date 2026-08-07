import { describe, expect, it } from "vitest";
import { csvToMarkdown } from "./csvToMarkdown";

describe("csvToMarkdown", () => {
  it("preserves a backslash immediately before a pipe inside one table cell", () => {
    const result = csvToMarkdown(["value,plain", String.raw`\|,ok`].join("\n"));
    const expected = [
      "| value | plain |",
      "| --- | --- |",
      String.raw`| \\\| | ok |`,
    ].join("\n");

    expect(result).toBe(expected);
  });
});
