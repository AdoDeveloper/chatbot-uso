"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

/* ── Tabs ── navegación por secciones, patrón `underline`.
 *
 * Bajo peso visual, escalable, jerárquicamente neutro — el patrón dominante en
 * dashboards modernos (Vercel, GitHub, Stripe, Linear).
 *
 * Para toggles mutuamente excluyentes (ambiente, rango de fecha) o filtros de
 * lista, usar `SegmentedControl`, no este componente. */

/* ── Context ── */
interface TabsContextValue {
  value: string
  onValueChange: (value: string) => void
}
const TabsCtx = React.createContext<TabsContextValue>({
  value: "",
  onValueChange: () => {},
})

function Tabs({
  value,
  onValueChange,
  defaultValue,
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & {
  value?: string
  onValueChange?: (value: string) => void
  defaultValue?: string
}) {
  const [internal, setInternal] = React.useState(defaultValue ?? "")
  const current = value ?? internal
  const onChange = onValueChange ?? setInternal

  return (
    <TabsCtx.Provider value={{ value: current, onValueChange: onChange }}>
      <div className={cn("flex flex-col", className)} {...props}>
        {children}
      </div>
    </TabsCtx.Provider>
  )
}

function TabsList({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      role="tablist"
      data-slot="tabs-list"
      className={cn(
        "flex items-center gap-0 border-b border-border w-full overflow-x-auto overflow-y-hidden",
        className
      )}
      {...props}
    />
  )
}

function TabsTrigger({
  value,
  className,
  ...props
}: React.ComponentProps<"button"> & { value: string }) {
  const ctx = React.useContext(TabsCtx)
  const isActive = ctx.value === value

  return (
    <button
      role="tab"
      type="button"
      aria-selected={isActive}
      data-state={isActive ? "active" : "inactive"}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 whitespace-nowrap text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50",
        "px-4 py-2.5 border-b-2 -mb-px [&_svg]:size-3.5",
        isActive
          ? "border-primary text-primary"
          : "border-transparent text-muted-foreground hover:text-foreground hover:border-border",
        className
      )}
      onClick={() => ctx.onValueChange(value)}
      {...props}
    />
  )
}

function TabsContent({
  value,
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { value: string }) {
  const ctx = React.useContext(TabsCtx)
  if (ctx.value !== value) return null

  return (
    <div
      role="tabpanel"
      data-slot="tabs-content"
      className={cn("mt-4 focus-visible:outline-none", className)}
      {...props}
    />
  )
}

export { Tabs, TabsList, TabsTrigger, TabsContent }
