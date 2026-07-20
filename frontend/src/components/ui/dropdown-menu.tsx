"use client"

import * as React from "react"
import { createPortal } from "react-dom"
import { cn } from "@/lib/utils"

/* ── Context ── */
interface DropdownContextValue {
  open: boolean
  setOpen: (open: boolean) => void
  wrapperRef: React.RefObject<HTMLDivElement | null>
  portalRef: React.RefObject<HTMLDivElement | null>
}
const DropdownCtx = React.createContext<DropdownContextValue>({ open: false, setOpen: () => {}, wrapperRef: { current: null }, portalRef: { current: null } })

function DropdownMenu({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = React.useState(false)
  const wrapperRef = React.useRef<HTMLDivElement>(null)
  const portalRef = React.useRef<HTMLDivElement | null>(null)

  React.useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      const target = e.target as Node
      const insideWrapper = wrapperRef.current?.contains(target)
      const insidePortal = portalRef.current?.contains(target)
      if (!insideWrapper && !insidePortal) setOpen(false)
    }
    document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [open])

  return (
    <DropdownCtx.Provider value={{ open, setOpen, wrapperRef, portalRef }}>
      <div ref={wrapperRef} className="relative inline-block">{children}</div>
    </DropdownCtx.Provider>
  )
}

function DropdownMenuTrigger({ children, className, asChild, ...props }: React.ComponentProps<"button"> & { asChild?: boolean }) {
  const { open, setOpen } = React.useContext(DropdownCtx)
  if (asChild && React.isValidElement(children)) {
    return React.cloneElement(children as React.ReactElement<{ onClick?: () => void; "aria-expanded"?: boolean }>, {
      onClick: () => setOpen(!open),
      "aria-expanded": open,
    })
  }
  return (
    <button
      type="button"
      aria-expanded={open}
      className={className}
      onClick={() => setOpen(!open)}
      {...props}
    >
      {children}
    </button>
  )
}

function DropdownMenuContent({ children, className, align = "end", side = "bottom", ...props }: React.HTMLAttributes<HTMLDivElement> & { align?: "start" | "end" | "center"; side?: "top" | "bottom" }) {
  const { open, wrapperRef, portalRef } = React.useContext(DropdownCtx)
  const [pos, setPos] = React.useState({ top: undefined as number | undefined, bottom: undefined as number | undefined, left: undefined as number | undefined, right: undefined as number | undefined })

  const updatePos = React.useCallback(() => {
    if (!wrapperRef.current) return
    const r = wrapperRef.current.getBoundingClientRect()
    const gap = 4

    const menuHeight = portalRef.current?.offsetHeight || 220
    const spaceBelow = window.innerHeight - r.bottom
    const spaceAbove = r.top
    let effectiveSide = side
    if (side === "bottom" && spaceBelow < menuHeight + gap && spaceAbove > spaceBelow) {
      effectiveSide = "top"
    } else if (side === "top" && spaceAbove < menuHeight + gap && spaceBelow > spaceAbove) {
      effectiveSide = "bottom"
    }

    const top = effectiveSide === "bottom" ? r.bottom + gap : undefined
    const bottom = effectiveSide === "top" ? window.innerHeight - r.top + gap : undefined

    let left: number | undefined
    let right: number | undefined
    if (align === "end") { left = undefined; right = window.innerWidth - r.right }
    else if (align === "start") { left = r.left; right = undefined }
    else { left = r.left + r.width / 2; right = undefined }

    setPos({ top, bottom, left, right })
  }, [align, side, wrapperRef])

  React.useLayoutEffect(() => {
    if (!open) return
    updatePos()
    const raf = requestAnimationFrame(updatePos)
    return () => cancelAnimationFrame(raf)
  }, [open, updatePos])

  React.useEffect(() => {
    if (!open) return
    updatePos()
    window.addEventListener("scroll", updatePos, true)
    window.addEventListener("resize", updatePos)
    return () => {
      window.removeEventListener("scroll", updatePos, true)
      window.removeEventListener("resize", updatePos)
    }
  }, [open, updatePos])

  if (!open) return null

  const content = (
    <div
      ref={(el) => { portalRef.current = el }}
      role="menu"
      className={cn(
        "fixed z-50 min-w-[8rem] max-w-[calc(100vw-1.5rem)] overflow-hidden rounded-md border bg-popover p-1 text-popover-foreground shadow-md animate-in fade-in-0 zoom-in-95",
        className
      )}
      style={{
        top: pos.top,
        bottom: pos.bottom,
        left: pos.left,
        right: pos.right,
        transform: align === "center" && pos.left != null ? "translateX(-50%)" : undefined,
      }}
      {...props}
    >
      {children}
    </div>
  )

  // En SSR (typeof document === "undefined") no hacemos portal, renderizamos
  // inline para que hidrate sin error, aunque el menú solo se abre en cliente.
  if (typeof document === "undefined") return content
  return createPortal(content, document.body)
}

function DropdownMenuItem({ className, onClick, disabled, ...props }: React.ComponentProps<"button">) {
  const { setOpen } = React.useContext(DropdownCtx)
  return (
    <button
      role="menuitem"
      type="button"
      disabled={disabled}
      data-disabled={disabled || undefined}
      className={cn(
        "relative flex w-full cursor-pointer select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none transition-colors hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50 [&_svg]:size-4",
        className
      )}
      onClick={(e) => { onClick?.(e); setOpen(false) }}
      {...props}
    />
  )
}

function DropdownMenuSeparator({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div role="separator" className={cn("-mx-1 my-1 h-px bg-border", className)} {...props} />
}

function DropdownMenuLabel({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-2 py-1.5 text-sm font-semibold", className)} {...props} />
}

function useDropdownMenu() {
  return React.useContext(DropdownCtx)
}

export { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuLabel, useDropdownMenu }
