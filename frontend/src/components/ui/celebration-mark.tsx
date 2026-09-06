import type { CSSProperties } from "react";
import { CircleCheck } from "lucide-react";

export function CelebrationMark() {
  return <span className="celebration-mark" aria-hidden="true"><CircleCheck strokeWidth={2.5} /><span className="celebration-particles">
    {Array.from({ length: 16 }, (_, i) => <i key={i} style={{
      "--x": `${Math.cos(i * 2.4) * (26 + i * 2)}px`,
      "--y": `${Math.sin(i * 2.4) * 40 + 8}px`,
      "--turn": `${i * 47}deg`,
      "--color": ["var(--brand-green)", "var(--brand-yellow)", "var(--brand-blue)", "var(--brand-orange)"][i % 4],
    } as CSSProperties} />)}
  </span></span>;
}
