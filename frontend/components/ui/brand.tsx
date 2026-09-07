/**
 * Brand lockup for the quiz platform: the real ArivuPro logo with a "Quiz
 * Platform" mark stacked beneath it — so it stays on-brand and fits narrow and
 * wide spaces alike (no horizontal clipping).
 *
 * The source logo is 814×158, so rendering it at ~34–40px tall stays crisp.
 * Designed for LIGHT surfaces (login / signup cards). For the dark green sidebar
 * the logo sits in its own white pill (handled there), since the logo art needs
 * a light background.
 */
import Image from "next/image";

const LOGO_ASPECT = 814 / 158;

export function Brand({
  height = 36,
  className,
}: {
  height?: number;
  className?: string;
}) {
  return (
    <span className={`inline-flex flex-col items-center gap-1.5 ${className ?? ""}`}>
      <Image
        src="/arivu-logo.png"
        alt="ArivuPro Academy"
        width={Math.round(height * LOGO_ASPECT)}
        height={height}
        className="w-auto"
      />
      <span className="text-[10px] font-bold uppercase tracking-[0.22em] text-[#2E8857]">
        Quiz Platform
      </span>
    </span>
  );
}
