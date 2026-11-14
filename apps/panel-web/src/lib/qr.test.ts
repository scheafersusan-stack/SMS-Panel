import { describe, expect, it } from "vitest";
import { qrDataUrl } from "./qr";

describe("qrDataUrl", () => {
  it("renders an image data URL from the library", () => {
    expect(qrDataUrl("otpauth://totp/x?secret=ABC")).toMatch(/^data:image\/gif;base64,/);
  });
});
