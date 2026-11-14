import { describe, expect, it } from "vitest";
import { formatMobile, normalizeMobile } from "./phone";

describe("phone", () => {
  it("normalises Iranian mobile numbers", () => {
    expect(normalizeMobile("09123456789")).toBe("09123456789");
    expect(normalizeMobile("+989123456789")).toBe("09123456789");
    expect(normalizeMobile("00989123456789")).toBe("09123456789");
    expect(normalizeMobile("9123456789")).toBe("09123456789");
    expect(normalizeMobile("۰۹۱۲۳۴۵۶۷۸۹")).toBe("09123456789");
    expect(normalizeMobile("0912 345 6789")).toBe("09123456789");
  });
  it("rejects invalid numbers", () => {
    expect(normalizeMobile("0812345678")).toBeNull();
    expect(normalizeMobile("0912345")).toBeNull();
    expect(normalizeMobile("")).toBeNull();
  });
  it("formats for display", () => {
    expect(formatMobile("+989123456789")).toBe("0912 345 6789");
    expect(formatMobile("bad")).toBe("bad");
  });
});
