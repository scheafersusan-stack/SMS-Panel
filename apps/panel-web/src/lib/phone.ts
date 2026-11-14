const AR_FA: Record<string, string> = {};
"۰۱۲۳۴۵۶۷۸۹".split("").forEach((c, i) => (AR_FA[c] = String(i)));
"٠١٢٣٤٥٦٧٨٩".split("").forEach((c, i) => (AR_FA[c] = String(i)));

/** Returns the canonical 09xxxxxxxxx form, or null when the input is not an Iranian mobile. */
export function normalizeMobile(input: string): string | null {
  let s = input.replace(/[۰-۹٠-٩]/g, (c) => AR_FA[c] ?? c).replace(/[\s\-().]/g, "");
  if (s.startsWith("+98")) s = s.slice(3);
  else if (s.startsWith("0098")) s = s.slice(4);
  else if (s.startsWith("98") && s.length === 12) s = s.slice(2);
  else if (s.startsWith("0")) s = s.slice(1);
  return /^9\d{9}$/.test(s) ? `0${s}` : null;
}

/** «0912 345 6789» for display; callers render it LTR. Invalid input is returned unchanged. */
export function formatMobile(input: string): string {
  const n = normalizeMobile(input);
  return n ? `${n.slice(0, 4)} ${n.slice(4, 7)} ${n.slice(7)}` : input;
}
