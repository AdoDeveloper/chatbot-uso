"use client"

import * as React from "react"
import { cn } from "@/lib/utils"
import { lockBodyScroll, unlockBodyScroll } from "@/lib/body-scroll-lock"
import { X } from "lucide-react"

/* ── Context ── */
interface DialogContextValue {
  open: boolean
  onOpenChange: (open: boolean) => void
}
const DialogCtx = React.createContext<DialogContextValue>({ open: false, onOpenChange: () => {} })

/* ── Root ── */
function Dialog({
  open,
  onOpenChange,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  children: React.ReactNode
}) {
  return (
    <DialogCtx.Provider value={{ open, onOpenChange }}>
      {children}
    </DialogCtx.Provider>
  )
}

/* ── Trigger ── */
function DialogTrigger({ children, asChild, ...props }: React.ComponentProps<"button"> & { asChild?: boolean }) {
  const { onOpenChange } = React.useContext(DialogCtx)
  if (asChild && React.isValidElement(children)) {
    return React.cloneElement(children as React.ReactElement<{ onClick?: () => void }>, {
      onClick: () => onOpenChange(true),
    })
  }
  return <button type="button" onClick={() => onOpenChange(true)} {...props}>{children}</button>
}

/* ── Content ── */
function DialogContent({
  children,
  className,
  hideCloseButton,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { hideCloseButton?: boolean }) {
  const { open, onOpenChange } = React.useContext(DialogCtx)
  const triggerRef = React.useRef<HTMLElement | null>(null)
  const onOpenChangeRef = React.useRef(onOpenChange)
  onOpenChangeRef.current = onOpenChange

  React.useEffect(() => {
    if (!open) return
    triggerRef.current = document.activeElement as HTMLElement | null
  }, [open])

  React.useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onOpenChangeRef.current(false) }
    document.addEventListener("keydown", handler)
    lockBodyScroll()
    return () => {
      document.removeEventListener("keydown", handler)
      unlockBodyScroll()
      triggerRef.current?.focus?.()
    }
  }, [open])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="fixed inset-0 bg-black/50 animate-in fade-in-0" onClick={() => onOpenChange(false)} />
      <div
        role="dialog"
        aria-modal="true"
        className={cn(
          "relative z-50 w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-xl border bg-card p-6 shadow-lg animate-in fade-in-0 zoom-in-95 duration-200",
          className
        )}
        {...props}
      >
        {children}
        {!hideCloseButton && (
          <button
            className="absolute right-4 top-4 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
            onClick={() => onOpenChange(false)}
            aria-label="Cerrar"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
    </div>
  )
}

/* ── Sub-components ── */
function DialogHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col gap-2 text-center sm:text-left", className)} {...props} />
}

function DialogFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col-reverse sm:flex-row sm:justify-end gap-2 pt-4", className)} {...props} />
}

function DialogTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h2 className={cn("text-lg font-semibold leading-none tracking-tight", className)} {...props} />
}

function DialogDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-sm text-muted-foreground", className)} {...props} />
}

export { Dialog, DialogTrigger, DialogContent, DialogHeader, DialogFooter, DialogTitle, DialogDescription }
