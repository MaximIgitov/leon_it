import { cn } from "@/lib/utils";
import { useId } from "react";

export function LogoGlyph({ className, shimmer = false }: { className?: string; shimmer?: boolean }) {
  const id = useId().replaceAll(":", "");
  return <svg viewBox="0 0 64 64" aria-hidden="true" className={cn("logo-glyph", shimmer && "logo-shimmer", className)}>
    <defs>
      <mask id={`${id}-shape`}><path d="M32 6C16 6 5 16 5 30c0 7 3 13 8 18l-4 10 15-5c3 1 5 1 8 1 16 0 27-10 27-24S48 6 32 6Z" fill="white" /><ellipse cx="24" cy="27" rx="3" ry="4" fill="black" /><ellipse cx="42" cy="27" rx="3" ry="4" fill="black" /><path d="M23 38q10 10 20-1" stroke="black" strokeWidth="4" strokeLinecap="round" fill="none" /></mask>
      <linearGradient id={`${id}-shine`}><stop stopColor="white" stopOpacity="0" /><stop offset=".5" stopColor="white" stopOpacity=".8" /><stop offset="1" stopColor="white" stopOpacity="0" /></linearGradient>
    </defs>
    <g mask={`url(#${id}-shape)`}><rect width="64" height="64" fill="currentColor" />{shimmer && <rect className="logo-shimmer-sweep" x="-48" width="48" height="64" fill={`url(#${id}-shine)`} />}</g>
  </svg>;
}

export function LogoMark({ size = 36, className }: { size?: number; className?: string }) {
  return <img src="/brand/logo.png" width={size} height={size} alt="LeonIT" className={cn("logo-mark shrink-0", className)} />;
}

export function LogoWordmark({ height = 28, className }: { height?: number; className?: string }) {
  return <span className={cn("logo-wordmark", className)} style={{ fontSize: height }} aria-label="LeonIT">leon<span className="logo-it">it</span><span className="logo-dot">.</span></span>;
}

export function Logo({ size = 36, wordmark = true, className }: { size?: number; wordmark?: boolean; className?: string }) {
  return <span className={cn("inline-flex items-center gap-2", className)}><LogoMark size={size} />{wordmark && <LogoWordmark height={Math.round(size * .86)} />}</span>;
}
