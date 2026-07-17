"use client"

import * as React from "react"
import { cn } from "@/lib/utils"
import { lockBodyScroll, unlockBodyScroll } from "@/lib/body-scroll-lock"
import { X } from "lucide-react"

/* ── Context ── */
interface SheetContextValue {
  open: boolean
  onOpenChange: (open: boolean) => void
}
const SheetCtx = React.createContext<SheetContextValue>({ open: false, onOpenChange: () => {} })

/* ── Root ── */
function Sheet({
  open,
  onOpenChange,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  children: React.ReactNode
}) {
  return (
    <SheetCtx.Provider value={{ open, onOpenChange }}>
      {children}
    </SheetCtx.Provider>
  )
}

/* ── Trigger ── */
function SheetTrigger({ children, ...props }: React.ComponentProps<"button">) {
  const { onOpenChange } = React.useContext(SheetCtx)
  return <button type="button" onClick={() => onOpenChange(true)} {...props}>{children}</button>
}

/* ── Content ── */
const sheetVariants = {
  right: "inset-y-0 right-0 h-full w-3/4 max-w-sm border-l translate-x-full data-[open=true]:translate-x-0",
  left: "inset-y-0 left-0 h-full w-3/4 max-w-sm border-r -translate-x-full data-[open=true]:translate-x-0",
  top: "inset-x-0 top-0 w-full border-b -translate-y-full data-[open=true]:translate-y-0",
  bottom: "inset-x-0 bottom-0 w-full border-t translate-y-full data-[open=true]:translate-y-0",
} as const

function SheetContent({
  children,
  className,
  side = "right",
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { side?: keyof typeof sheetVariants }) {
  const { open, onOpenChange } = React.useContext(SheetCtx)

  React.useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onOpenChange(false) }
    document.addEventListener("keydown", handler)
    lockBodyScroll()
    return () => { document.removeEventListener("keydown", handler); unlockBodyScroll() }
  }, [open, onOpenChange])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50">
      <div className="fixed inset-0 bg-black/50 animate-in fade-in-0" onClick={() => onOpenChange(false)} />
      <div
        role="dialog"
        aria-modal="true"
        data-open={open}
        className={cn(
          "fixed z-50 bg-card p-6 shadow-lg transition-transform duration-300 ease-in-out",
          sheetVariants[side],
          className
        )}
        {...props}
      >
        {children}
        <button
          className="absolute right-4 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring"
          onClick={() => onOpenChange(false)}
          aria-label="Cerrar"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}

function SheetHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col gap-2 mb-4", className)} {...props} />
}

function SheetTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h2 className={cn("text-lg font-semibold", className)} {...props} />
}

function SheetDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-sm text-muted-foreground", className)} {...props} />
}

export { Sheet, SheetTrigger, SheetContent, SheetHeader, SheetTitle, SheetDescription }
