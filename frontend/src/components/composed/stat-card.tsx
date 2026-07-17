"use client"

import * as React from "react"
import { cn } from "@/lib/utils"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { HelpTip } from "@/components/ui/help-tip"
import { TrendingUp, TrendingDown, Minus } from "lucide-react"

interface StatCardProps {
  title: string
  value: string | number
  description?: string
  delta?: number | null
  deltaLabel?: string
  icon?: React.ComponentType<{ className?: string }>
  valueIcon?: React.ComponentType<{ className?: string }>
  tip?: React.ReactNode
  loading?: boolean
  className?: string
  accent?: "primary" | "teal" | "green" | "amber" | "red"
  /** Texto largo (fechas, nombres) en vez de una cifra corta: usa un tamaño de valor menor. */
  compact?: boolean
}

// Stripe / Linear pattern: subtle icon chip, no heavy left-border. Border
// stays canonical so the card sits in the same visual rhythm as everything
// else on the page.
const ACCENT_MAP = {
  primary: { bg: "bg-primary/10", text: "text-primary" },
  teal:    { bg: "bg-brand-teal/10", text: "text-brand-teal" },
  green:   { bg: "bg-brand-green/12", text: "text-brand-green" },
  amber:   { bg: "bg-warning/10", text: "text-warning" },
  red:     { bg: "bg-destructive/10", text: "text-destructive" },
}

function StatCard({
  title,
  value,
  description,
  delta,
  deltaLabel,
  icon: Icon,
  valueIcon: ValueIcon,
  tip,
  loading,
  className,
  accent = "primary",
  compact = false,
}: StatCardProps) {
  const colors = ACCENT_MAP[accent]

  if (loading) {
    return (
      <Card className={cn("p-4", className)}>
        <Skeleton className="h-3 w-20 mb-3" />
        <Skeleton className="h-7 w-16 mb-2" />
        <Skeleton className="h-3 w-28" />
      </Card>
    )
  }

  const deltaClass =
    delta == null ? "" :
    delta > 0 ? "text-brand-green bg-brand-green/10" :
    delta < 0 ? "text-destructive bg-destructive/10" :
    "text-muted-foreground bg-muted"

  const DeltaIcon =
    delta == null ? null :
    delta > 0 ? TrendingUp :
    delta < 0 ? TrendingDown :
    Minus

  return (
    <Card className={cn("p-4", className)}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1">
            <p className="text-2xs font-semibold uppercase tracking-wider text-muted-foreground truncate">
              {title}
            </p>
            {tip && <HelpTip description={tip} side="bottom" align="start" />}
          </div>
          <div className="mt-2 flex items-center gap-2 flex-wrap">
            {ValueIcon && <ValueIcon className={cn("h-4 w-4 shrink-0", colors.text)} />}
            <span className={cn(
              "font-semibold tracking-tight",
              ValueIcon || compact ? "text-sm leading-tight" : "text-2xl leading-none tabular-nums"
            )}>
              {value}
            </span>
            {delta != null && DeltaIcon && (
              <span className={cn(
                "inline-flex items-center gap-0.5 text-2xs font-semibold px-1.5 py-0.5 rounded-md",
                deltaClass
              )}>
                <DeltaIcon className="h-3 w-3" />
                {Math.abs(delta)}%
              </span>
            )}
          </div>
          {(description || deltaLabel) && (
            <p className="mt-1.5 text-[11.5px] text-muted-foreground leading-snug">
              {deltaLabel || description}
            </p>
          )}
        </div>
        {Icon && (
          <div className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", colors.bg)}>
            <Icon className={cn("h-[18px] w-[18px]", colors.text)} />
          </div>
        )}
      </div>
    </Card>
  )
}

export { StatCard }
export type { StatCardProps }
