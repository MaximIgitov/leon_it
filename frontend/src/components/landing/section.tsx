import { cn } from "@/lib/utils";

/*
 * Секция лендинга: якорь для навигации, заголовок второго уровня и отступы.
 * Заголовок связан с секцией через aria-labelledby, чтобы скринридер
 * объявлял её по имени.
 */
export function Section({
  id,
  eyebrow,
  title,
  lead,
  tone = "default",
  className,
  children,
}: {
  id: string;
  eyebrow?: string;
  title: string;
  lead?: string;
  tone?: "default" | "muted";
  className?: string;
  children: React.ReactNode;
}) {
  const titleId = `${id}-title`;
  return (
    <section
      id={id}
      aria-labelledby={titleId}
      className={cn("scroll-mt-20 py-16 sm:py-24", tone === "muted" && "bg-muted/40", className)}
    >
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <div className="max-w-2xl">
          {eyebrow ? <p className="text-sm font-semibold text-primary">{eyebrow}</p> : null}
          <h2 id={titleId} className="mt-2 text-balance text-3xl font-bold tracking-tight sm:text-4xl">
            {title}
          </h2>
          {lead ? <p className="mt-4 text-pretty text-lg text-muted-foreground">{lead}</p> : null}
        </div>
        <div className="mt-10 sm:mt-12">{children}</div>
      </div>
    </section>
  );
}

export function IconChip({ icon: Icon, className }: { icon: React.ElementType; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary",
        className,
      )}
      aria-hidden="true"
    >
      <Icon className="h-5 w-5" />
    </span>
  );
}
