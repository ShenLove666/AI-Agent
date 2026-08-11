import { describe, expect, it, vi } from "vitest";

import { formatFullDateTime, formatRelativeTime, parseApiDate } from "@/utils/time";

describe("parseApiDate（兼容 naive UTC 与带时区串）", () => {
  it("naive UTC（无 Z/±hh:mm）→ 补 Z 按 UTC 解析", () => {
    // 本地 UTC+8：naive "06:29" 若当本地解析会差 8 小时；补 Z 后按 UTC 正确解析
    const date = parseApiDate("2026-08-11T06:29:00");
    expect(date.toISOString()).toBe("2026-08-11T06:29:00.000Z");
  });

  it("带 Z 的串原样解析", () => {
    expect(parseApiDate("2026-08-11T06:29:00Z").toISOString()).toBe("2026-08-11T06:29:00.000Z");
  });

  it("带 +00:00 偏移的串原样解析", () => {
    expect(parseApiDate("2026-08-11T06:29:00+00:00").toISOString()).toBe("2026-08-11T06:29:00.000Z");
  });

  it("带非零偏移的串按偏移解析", () => {
    expect(parseApiDate("2026-08-11T14:29:00+08:00").toISOString()).toBe("2026-08-11T06:29:00.000Z");
  });
});

describe("formatFullDateTime（UTC+8 本地展示）", () => {
  it("naive UTC 06:29 → 本地 14:29（不再差 8 小时）", () => {
    const result = formatFullDateTime("2026-08-11T06:29:00");
    expect(result).toContain("14:29");
  });

  it("带 Z 的串同样正确", () => {
    expect(formatFullDateTime("2026-08-11T06:29:00Z")).toContain("14:29");
  });
});

describe("formatRelativeTime", () => {
  it("naive UTC 时间按 UTC 解析后计算相对时间", () => {
    // 固定「现在」= 2026-08-11T08:00:00Z（本地 16:00）
    vi.setSystemTime(new Date("2026-08-11T08:00:00Z"));
    // naive UTC 07:00 = 1 小时前（若按本地解析会变成 9 小时前）
    expect(formatRelativeTime("2026-08-11T07:00:00")).toBe("1 小时前");
  });
});
