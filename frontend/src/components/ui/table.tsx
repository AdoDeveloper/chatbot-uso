"use client"

import * as React from "react"
import { cn } from "@/lib/utils"
import { ScrollShadow } from "@/components/composed/scroll-shadow"

// `min-w-full` deja que la tabla crezca y active el scroll horizontal del ScrollShadow; las columnas ocultas en mobile no fuerzan ese scroll.
function Table({ className, ...props }: React.HTMLAttributes<HTMLTableElement>) {
  return (
    <ScrollShadow className="w-full">
      <table data-slot="table" className={cn("min-w-full caption-bottom text-sm", className)} {...props} />
    </ScrollShadow>
  )
}

function TableHeader({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <thead data-slot="table-header" className={cn("[&_tr]:border-b", className)} {...props} />
}

function TableBody({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody data-slot="table-body" className={cn("[&_tr:last-child]:border-0", className)} {...props} />
}

function TableFooter({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tfoot data-slot="table-footer" className={cn("border-t bg-muted/50 font-medium [&>tr]:last:border-b-0", className)} {...props} />
}

function TableRow({ className, ...props }: React.HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      data-slot="table-row"
      className={cn("group border-b border-border/60 transition-colors hover:bg-muted/40 data-[state=selected]:bg-muted", className)}
      {...props}
    />
  )
}

// `sticky` fija la columna "Acciones" al borde derecho para que sea alcanzable sin desplazarse hasta el final en mobile.
function TableHead({ className, sticky, ...props }: React.ThHTMLAttributes<HTMLTableCellElement> & { sticky?: boolean }) {
  return (
    <th
      data-slot="table-head"
      className={cn(
        "h-9 px-3 text-left align-middle text-2xs font-semibold uppercase tracking-wider text-muted-foreground bg-muted [&:has([role=checkbox])]:pr-0 [&>[role=checkbox]]:translate-y-[2px]",
        // max-w-* no basta en table-layout auto (una columna sin `width` absorbe el espacio sobrante); w-28 es el ancho medido que sí lo restringe.
        sticky && "sticky right-0 z-10 w-28 border-l border-border/60 shadow-[-4px_0_6px_-4px_rgb(0_0_0/0.12)]",
        className
      )}
      {...props}
    />
  )
}

function TableCell({ className, sticky, ...props }: React.TdHTMLAttributes<HTMLTableCellElement> & { sticky?: boolean }) {
  return (
    <td
      data-slot="table-cell"
      className={cn(
        "px-3 py-2 align-middle text-13 [&:has([role=checkbox])]:pr-0 [&>[role=checkbox]]:translate-y-[2px]",
        sticky && "sticky right-0 z-10 w-28 bg-card border-l border-border/60 shadow-[-4px_0_6px_-4px_rgb(0_0_0/0.12)] group-hover:bg-muted/40",
        className
      )}
      {...props}
    />
  )
}

function TableCaption({ className, ...props }: React.HTMLAttributes<HTMLTableCaptionElement>) {
  return <caption data-slot="table-caption" className={cn("mt-4 text-sm text-muted-foreground", className)} {...props} />
}

export { Table, TableHeader, TableBody, TableFooter, TableHead, TableRow, TableCell, TableCaption }
