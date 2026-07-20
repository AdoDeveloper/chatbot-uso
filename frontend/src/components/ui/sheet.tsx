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

// Mapea cada `side` al eje/signo de swipe que debe cerrarlo: un sheet que
// entra desde la izquierda se cierra deslizando hacia la izquierda, uno
// desde arriba se cierra deslizando hacia arriba, etc.
const SWIPE_CLOSE_DIRECTION: Record<keyof typeof sheetVariants, "x" | "y"> = {
  left: "x",
  right: "x",
  top: "y",
  bottom: "y",
}
const SWIPE_CLOSE_SIGN: Record<keyof typeof sheetVariants, 1 | -1> = {
  left: -1,
  right: 1,
  top: -1,
  bottom: 1,
}
const SWIPE_CLOSE_THRESHOLD = 60

function SheetContent({
  children,
  className,
  side = "right",
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { side?: keyof typeof sheetVariants }) {
  const { open, onOpenChange } = React.useContext(SheetCtx)
  const panelRef = React.useRef<HTMLDivElement>(null)
  const dragState = React.useRef<{ startX: number; startY: number; dragging: boolean } | null>(null)
  const [dragOffset, setDragOffset] = React.useState(0)
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

  React.useEffect(() => { if (!open) setDragOffset(0) }, [open])

  const axis = SWIPE_CLOSE_DIRECTION[side]
  const sign = SWIPE_CLOSE_SIGN[side]

  const onTouchStart = (e: React.TouchEvent) => {
    const t = e.touches[0]
    dragState.current = { startX: t.clientX, startY: t.clientY, dragging: false }
  }

  const onTouchMove = (e: React.TouchEvent) => {
    const state = dragState.current
    if (!state) return
    const t = e.touches[0]
    const dx = t.clientX - state.startX
    const dy = t.clientY - state.startY
    if (!state.dragging) {
      const primary = axis === "x" ? Math.abs(dx) : Math.abs(dy)
      const secondary = axis === "x" ? Math.abs(dy) : Math.abs(dx)
      if (primary < 10 || primary < secondary) return
      state.dragging = true
    }
    const delta = axis === "x" ? dx : dy
    // Solo se sigue el dedo en la dirección que cierra el sheet; en la
    // dirección contraria no se mueve (no "sobre-abre" más allá de su
    // posición final).
    const closing = delta * sign > 0
    setDragOffset(closing ? delta : 0)
  }

  const onTouchEnd = () => {
    const state = dragState.current
    dragState.current = null
    if (!state?.dragging) return
    if (Math.abs(dragOffset) > SWIPE_CLOSE_THRESHOLD) {
      onOpenChange(false)
    } else {
      setDragOffset(0)
    }
  }

  if (!open) return null

  const dragTransform =
    dragOffset !== 0
      ? axis === "x"
        ? `translateX(${dragOffset}px)`
        : `translateY(${dragOffset}px)`
      : undefined

  return (
    <div className="fixed inset-0 z-50">
      <div className="fixed inset-0 bg-black/50 animate-in fade-in-0" onClick={() => onOpenChange(false)} />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        data-open={open}
        className={cn(
          "fixed z-50 bg-card p-6 shadow-lg transition-transform duration-300 ease-in-out",
          sheetVariants[side],
          className
        )}
        style={dragTransform ? { transform: dragTransform, transitionDuration: "0ms" } : undefined}
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
        onTouchCancel={onTouchEnd}
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
