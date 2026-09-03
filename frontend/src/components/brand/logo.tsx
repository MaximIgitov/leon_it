import { cn } from "@/lib/utils";

/*
 * Логотип LeonIT.
 *
 * Знак — геометрическая «L» в духе фирменной «N» Napoleon IT: тот же тяжёлый
 * гротеск, тот же квадрат-подложка. Вордмарк «LEON IT» вырезан из вордмарка
 * «NAPOLEON IT» (napoleonit.ru): глифы L, E, O, N, I, T взяты с оригинальными
 * контурами и сдвинуты к нулю, поэтому начертание совпадает с брендом.
 */

export function LogoMark({
  size = 32,
  className,
}: {
  size?: number;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 256 256"
      width={size}
      height={size}
      className={cn("shrink-0", className)}
      role="img"
      aria-label="LeonIT"
    >
      <rect width="256" height="256" rx="56" style={{ fill: "hsl(var(--primary))" }} />
      <path
        d="M66 50h34v122h90v34H66V50z"
        style={{ fill: "hsl(var(--primary-foreground))" }}
      />
    </svg>
  );
}

const WORDMARK_PATHS = [
  // L
  "M62.3105 0H64.1657V9.85328H70.5279V11.5H62.3105V0Z",
  // E
  "M84.395 0V1.63076H77.6052V4.97698H83.3373V6.60774H77.6052V9.78312H84.395V11.5H75.6641V0H84.395Z",
  // O
  "M89.5368 5.59327C89.4504 8.66899 90.9147 10.9747 93.5826 11.7433C94.5357 12.013 95.537 12.0711 96.5153 11.9133C99.3474 11.4862 101.157 9.26615 101.33 6.19184C101.534 3.4111 99.7324 0.873744 97.025 0.12751C96.0284 -0.0425034 95.0097 -0.0425034 94.013 0.12751C91.406 0.669804 89.5384 2.95026 89.5368 5.59327ZM95.562 1.91916C97.7725 1.99094 99.5059 3.82721 99.4336 6.02059V6.35781C99.3946 7.78165 98.5905 9.07586 97.326 9.75007C96.0614 10.4243 94.53 10.3754 93.3118 9.62184C92.0936 8.86831 91.3751 7.52546 91.4285 6.10208V5.76065C91.5008 3.56727 93.3515 1.84738 95.562 1.91916Z",
  // N
  "M108.84 3.91697V11.3341H106.996V0C107.348 0.250894 112.79 5.16732 115.337 7.50078V0.167263H117.268V11.5C116.917 11.2505 111.912 6.6672 109.63 4.58327L108.84 3.91697Z",
  // I
  "M128.051 11.5V0H130.105V11.4181H128.051V11.5Z",
  // T
  "M139.181 11.5V1.71547H135.242V0H145V1.63076H141.159V11.5H139.181Z",
];

export function LogoWordmark({
  height = 12,
  className,
}: {
  height?: number;
  className?: string;
}) {
  const width = (height * 82.7) / 12;
  return (
    <svg
      viewBox="0 0 82.7 12"
      width={width}
      height={height}
      className={cn("shrink-0", className)}
      role="img"
      aria-label="LeonIT"
    >
      <g transform="translate(-62.3105 0)" fill="currentColor">
        {WORDMARK_PATHS.map((d) => (
          <path key={d.slice(0, 12)} d={d} fillRule="evenodd" clipRule="evenodd" />
        ))}
      </g>
    </svg>
  );
}

export function Logo({
  size = 28,
  wordmark = true,
  className,
}: {
  size?: number;
  wordmark?: boolean;
  className?: string;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark size={size} />
      {wordmark ? <LogoWordmark height={Math.round(size * 0.42)} /> : null}
    </span>
  );
}
