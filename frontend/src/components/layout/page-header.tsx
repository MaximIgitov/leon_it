import { cn } from "@/lib/utils";

export function PageHeader({
  title,
  description,
  actions,
  className,
  icon,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  className?: string;
  icon?: React.ReactNode;
}) {
  return (
    <div className={cn("page-heading flex flex-wrap items-start justify-between gap-4", className)}>
      <div className="min-w-0 flex items-center gap-4">
        {icon}<div className="min-w-0">
        <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{title}</h1>
        {description ? <p className="mt-1 text-muted-foreground">{description}</p> : null}
        </div>
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}
