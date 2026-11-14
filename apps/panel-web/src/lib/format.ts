const FA = "۰۱۲۳۴۵۶۷۸۹";
const TZ = "Asia/Tehran";
export const THOUSANDS = "٬";

export function faDigits(n: number | string): string {
  return String(n).replace(/\d/g, (d) => FA[Number(d)] ?? d);
}

export function faNumber(n: number | string): string {
  if (typeof n === "number" && !Number.isFinite(n)) return "—";
  // BigInt keeps large integers out of exponent form.
  const s = typeof n === "number" && Number.isInteger(n) ? BigInt(n).toString() : String(n);
  const m = /^(-?)(\d+)(\.\d+)?$/.exec(s);
  if (!m) return faDigits(s);
  const grouped = (m[2] ?? "").replace(/\B(?=(\d{3})+(?!\d))/g, THOUSANDS);
  return faDigits(`${m[1] ?? ""}${grouped}${(m[3] ?? "").replace(".", "٫")}`);
}

const dateFmt = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  timeZone: TZ,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});
const timeFmt = new Intl.DateTimeFormat("fa-IR-u-ca-persian", {
  timeZone: TZ,
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

function toDate(d: Date | string): Date {
  return typeof d === "string" ? new Date(d) : d;
}

function parts(fmt: Intl.DateTimeFormat, d: Date): Record<string, string> {
  const out: Record<string, string> = {};
  for (const p of fmt.formatToParts(d)) out[p.type] = p.value;
  return out;
}

/** Jalali date, e.g. «۱۴۰۵/۰۸/۲۱» (Persian digits, Tehran time). */
export function jalaliDate(d: Date | string): string {
  const date = toDate(d);
  if (Number.isNaN(date.getTime())) return "";
  const p = parts(dateFmt, date);
  return `${p.year}/${p.month}/${p.day}`;
}

/** Jalali date and 24-hour time, e.g. «۱۴۰۵/۰۸/۲۱ ۱۰:۳۰». */
export function jalaliDateTime(d: Date | string): string {
  const date = toDate(d);
  if (Number.isNaN(date.getTime())) return "";
  const p = parts(timeFmt, date);
  return `${jalaliDate(date)} ${p.hour}:${p.minute}`;
}

export type MoneyUnit = "ریال" | "تومان";

/** Amounts are stored in rials; toman is rials / 10, rounded to the nearest toman (half away from zero). */
export function money(rials: number, unit: MoneyUnit = "ریال"): string {
  const v = unit === "تومان" ? Math.round(rials / 10) : rials;
  return `${faNumber(v)} ${unit}`;
}
