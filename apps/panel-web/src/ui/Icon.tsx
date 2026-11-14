import { ICONS } from "@/icons/icons.gen";

export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  return (
    <svg
      className="ns-icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: ICONS[name] ?? "" }}
    />
  );
}
