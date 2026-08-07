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

    expect(open).toHaveBeenCalledWith(
      "https://example.com/article",
      "_blank",
      "noopener,noreferrer"
    );
  });

  it("opens local sources in the document preview", () => {
    const open = stubWindowOpen();

    openSource({ docId: "42" });

    expect(open).toHaveBeenCalledWith("/preview/doc/42", "_blank", "noopener,noreferrer");
  });

  it("does not open a preview when the citation has no valid document id", () => {
    const open = stubWindowOpen();

    openSource({ docName: "legacy citation" });
    openSource({ docId: "undefined", docName: "broken citation" });

    expect(open).not.toHaveBeenCalled();
  });
});
