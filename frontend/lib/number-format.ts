/**
 * Show rupee amounts in Indian digit grouping (10,92,600), which Indian
 * readers expect. The model often writes international grouping for INR
 * ("1,092,600 INR") even when told not to, so this is done deterministically
 * at display time. Only numbers explicitly tied to ₹ / Rs. / INR change;
 * other currencies and bare numbers keep international grouping.
 */
const GROUPED = String.raw`\d{1,3}(?:,\d{2,3})+(?:\.\d+)?`;
const RUPEE_BEFORE = new RegExp(String.raw`((?:₹|\bRs\.?|\bINR)\s?)(${GROUPED})`, "g");
const RUPEE_AFTER = new RegExp(String.raw`(${GROUPED})(\s?(?:INR|rupees)\b)`, "g");

export function toIndianGrouping(amount: string): string {
  const [whole, fraction] = amount.replace(/,/g, "").split(".");
  const lastThree = whole.slice(-3);
  const rest = whole.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",");
  const grouped = rest ? `${rest},${lastThree}` : lastThree;
  return fraction !== undefined ? `${grouped}.${fraction}` : grouped;
}

export function indianiseRupeeAmounts(text: string): string {
  return text
    .split(/(```[\s\S]*?```|`[^`\n]*`)/g)
    .map((part, index) =>
      index % 2 === 1
        ? part
        : part
            .replace(RUPEE_BEFORE, (_m, prefix: string, amount: string) => prefix + toIndianGrouping(amount))
            .replace(RUPEE_AFTER, (_m, amount: string, suffix: string) => toIndianGrouping(amount) + suffix),
    )
    .join("");
}
