import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(process.cwd(), "src/styles/globals.css"), "utf8");

describe("sidebar scrollbar", () => {
  it("keeps a stable gutter when the pointer enters the scroll area", () => {
    expect(css).toMatch(
      /\.sidebar-scroll\s*\{[^}]*scrollbar-width:\s*thin;[^}]*scrollbar-gutter:\s*stable;/s
    );
    expect(css).toMatch(
      /\.sidebar-scroll::-webkit-scrollbar\s*\{[^}]*width:\s*4px;/s
    );
    expect(css).not.toMatch(
      /\.sidebar-scroll:hover::-webkit-scrollbar\s*\{[^}]*width:/s
    );
  });
});
