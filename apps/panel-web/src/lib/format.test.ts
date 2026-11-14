import { describe, expect, it } from "vitest";
import { faDigits, faNumber, jalaliDate, jalaliDateTime, money } from "./format";

describe("format", () => {
  it("converts digits to Persian", () => {
    expect(faDigits("0912")).toBe("۰۹۱۲");
    expect(faDigits(45)).toBe("۴۵");
  });
  it("groups with the Persian thousands separator", () => {
    expect(faNumber(1240)).toBe("۱٬۲۴۰");
    expect(faNumber(1845000)).toBe("۱٬۸۴۵٬۰۰۰");
    expect(faNumber(-1240)).toBe("-۱٬۲۴۰");
    expect(faNumber(12)).toBe("۱۲");
    expect(faNumber(NaN)).toBe("—");
    expect(faNumber(Infinity)).toBe("—");
    expect(faNumber(1e21)).toBe("۱٬۰۰۰٬۰۰۰٬۰۰۰٬۰۰۰٬۰۰۰٬۰۰۰٬۰۰۰");
    expect(faNumber("1240")).toBe("۱٬۲۴۰");
  });
  it("formats Jalali dates in the Tehran zone", () => {
    expect(jalaliDate("2026-11-12")).toBe("۱۴۰۵/۰۸/۲۱");
    expect(jalaliDate(new Date("2026-11-12T10:00:00Z"))).toBe("۱۴۰۵/۰۸/۲۱");
    // 21:00Z is already the next day in Tehran (UTC+3:30)
    expect(jalaliDate("2026-11-12T21:00:00Z")).toBe("۱۴۰۵/۰۸/۲۲");
  });
  it("formats Jalali date and time", () => {
    expect(jalaliDateTime("2026-11-12T07:00:00Z")).toBe("۱۴۰۵/۰۸/۲۱ ۱۰:۳۰");
  });
  it("formats money in rial or toman", () => {
    expect(money(1845000)).toBe("۱٬۸۴۵٬۰۰۰ ریال");
    expect(money(1845000, "ریال")).toBe("۱٬۸۴۵٬۰۰۰ ریال");
    expect(money(1845000, "تومان")).toBe("۱۸۴٬۵۰۰ تومان");
    expect(money(1845005, "تومان")).toBe("۱۸۴٬۵۰۱ تومان");
  });
});
