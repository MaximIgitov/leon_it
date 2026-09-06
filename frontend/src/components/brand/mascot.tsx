import { cn } from "@/lib/utils";

export type MascotName = "leo" | "mira" | "max" | "celebrate" | "listen" | "think" | "fox" | "rabbit" | "bear";

/** Персонажи с прозрачным фоном: на цветной сцене не нужен multiply, который тонирует картинку. */
const CUTOUT = new Set<MascotName>(["leo", "mira", "max", "listen", "think", "celebrate"]);

export function Mascot({ name = "leo", className, eager = false, alt = "", cutout = false }: {
  name?: MascotName;
  className?: string;
  eager?: boolean;
  alt?: string;
  cutout?: boolean;
}) {
  if (cutout && CUTOUT.has(name)) {
    return <img src={`/brand/mascot-${name}.png`} width={640} height={640} alt={alt} loading={eager ? "eager" : "lazy"} decoding="async" draggable={false} className={cn("mascot", className)} />;
  }
  const asset = name === "listen" ? "mira" : name === "think" ? "max" : name === "celebrate" ? "bear" : name;
  return <img src={`/brand/flat-${asset}.png`} width={640} height={640} alt={alt} loading={eager ? "eager" : "lazy"} decoding="async" draggable={false} className={cn("mascot", ["leo", "mira", "max"].includes(asset) && "mascot-human", className)} />;
}
