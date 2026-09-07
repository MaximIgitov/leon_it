import * as React from "react"

import { cn } from "@/lib/utils"

const Table = React.forwardRef<
  HTMLTableElement,
  React.HTMLAttributes<HTMLTableElement>
>(({ className, ...props }, ref) => (
  <div className="table-surface relative w-full overflow-auto rounded-2xl bg-surface code-scrollbar">
    <table
      ref={ref}
      className={cn("leon-table w-full caption-bottom text-sm font-normal", className)}
      {...props}
    />
  </div>
))
Table.displayName = "Table"

const TableHeader = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <thead ref={ref} className={cn("[&_tr]:border-b", className)} {...props} />
))
TableHeader.displayName = "TableHeader"

const TableBody = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tbody
    ref={ref}
    className={cn("[&_tr:last-child]:border-0", className)}
    {...props}
  />
))
TableBody.displayName = "TableBody"

const TableFooter = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tfoot
    ref={ref}
    className={cn(
      "border-t bg-secondary/50 font-medium [&>tr]:last:border-b-0",
      className
    )}
    {...props}
  />
))
TableFooter.displayName = "TableFooter"

// Элементы, клик по которым не должен вести по ссылке строки.
const ROW_INTERACTIVE =
  'a, button, input, select, textarea, label, summary, [role="button"], [role="checkbox"], [role="menuitem"], [contenteditable="true"]'

type RowLike = { querySelector: (selector: string) => Element | null }
type TargetLike = { closest: (selector: string) => Element | null } | null

/** Ссылка строки (`a.table-row-link`), если клик пришёлся не по другому интерактивному элементу. */
export function rowLinkTarget(row: RowLike, target: TargetLike): HTMLAnchorElement | null {
  const link = row.querySelector("a.table-row-link") as HTMLAnchorElement | null
  if (!link) return null
  if (target && target.closest(ROW_INTERACTIVE)) return null
  return link
}

const TableRow = React.forwardRef<
  HTMLTableRowElement,
  React.HTMLAttributes<HTMLTableRowElement>
>(({ className, onClick, ...props }, ref) => (
  <tr
    ref={ref}
    className={cn(
      "leon-table-row border-b transition-colors data-[state=selected]:bg-secondary",
      className
    )}
    onClick={(event) => {
      onClick?.(event)
      // Клик по строке = клик по её ссылке. Раньше это делал растянутый ::after
      // у ссылки, но tr как containing block и :has() работают не во всех
      // браузерах, и все клики по таблице уходили в последнюю строку.
      if (event.defaultPrevented || event.button !== 0) return
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
      if (typeof window !== "undefined" && window.getSelection()?.toString()) return
      const target = event.target instanceof Element ? event.target : null
      const link = rowLinkTarget(event.currentTarget, target)
      if (link) link.click()
    }}
    {...props}
  />
))
TableRow.displayName = "TableRow"

const TableHead = React.forwardRef<
  HTMLTableCellElement,
  React.ThHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => (
  <th
    ref={ref}
    className={cn(
      "h-12 px-4 text-left align-middle font-medium text-muted-foreground [&:has([role=checkbox])]:pr-0",
      className
    )}
    {...props}
  />
))
TableHead.displayName = "TableHead"

const TableCell = React.forwardRef<
  HTMLTableCellElement,
  React.TdHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => (
  <td
    ref={ref}
    className={cn("p-4 align-middle font-medium [&:has([role=checkbox])]:pr-0", className)}
    {...props}
  />
))
TableCell.displayName = "TableCell"

const TableCaption = React.forwardRef<
  HTMLTableCaptionElement,
  React.HTMLAttributes<HTMLTableCaptionElement>
>(({ className, ...props }, ref) => (
  <caption
    ref={ref}
    className={cn("mt-4 text-sm text-muted-foreground", className)}
    {...props}
  />
))
TableCaption.displayName = "TableCaption"

export {
  Table,
  TableHeader,
  TableBody,
  TableFooter,
  TableHead,
  TableRow,
  TableCell,
  TableCaption,
}
