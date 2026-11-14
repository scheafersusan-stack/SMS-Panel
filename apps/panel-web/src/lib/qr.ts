import qrcode from "qrcode-generator";

/** A GIF data URL of the QR code for `text`, produced entirely by the library. */
export function qrDataUrl(text: string): string {
  const qr = qrcode(0, "M");
  qr.addData(text);
  qr.make();
  return qr.createDataURL(5, 8);
}
