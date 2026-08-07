import { afterEach, describe, expect, it, vi } from "vitest";
import { openSource } from "./source";

function stubWindowOpen() {
  const open = vi.fn();
  vi.stubGlobal("window", { open });
  return open;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("openSource", () => {
  it("does not open unsupported URL protocols", () => {
    const open = stubWindowOpen();

    openSource({ docId: "unsafe-js", url: "javascript:alert(1)" });
    openSource({ docId: "unsafe-data", url: "data:text/html,unsafe" });

    expect(open).not.toHaveBeenCalled();
  });

  it("opens HTTP(S) sources in a new tab", () => {
    const open = stubWindowOpen();

    openSource({ docId: "external", url: "https://example.com/article" });

    expect(open).toHaveBeenCalledWith("https://example.com/article", "_blank", "noopener,noreferrer");
  });

  it("opens local sources in the document preview", () => {
    const open = stubWindowOpen();

    openSource({ docId: "local-document" });

    expect(open).toHaveBeenCalledWith("/preview/doc/local-document", "_blank", "noopener,noreferrer");
  });
});
