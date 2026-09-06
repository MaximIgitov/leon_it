import { cn } from "@/lib/utils";

export type MascotName = "leo" | "mira" | "max" | "celebrate" | "listen" | "think" | "fox" | "rabbit" | "bear";

export function Mascot({ name = "leo", className, eager = false, alt = "" }: {
  name?: MascotName;
  className?: string;
  eager?: boolean;
  alt?: string;
}) {
  const asset = name === "listen" ? "mira" : name === "think" ? "max" : name === "celebrate" ? "bear" : name;
  return <img src={`/brand/flat-${asset}.png`} width={640} height={640} alt={alt} loading={eager ? "eager" : "lazy"} decoding="async" draggable={false} className={cn("mascot", ["leo", "mira", "max"].includes(asset) && "mascot-human", className)} />;
}
