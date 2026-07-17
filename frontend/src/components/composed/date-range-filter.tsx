"use client"

import * as React from "react"
import { cn } from "@/lib/utils"
import { Input } from "@/components/ui/input"

interface DateRangeFilterProps {
  from: string
  to: string
  onFromChange: (value: string) => void
  onToChange: (value: string) => void
  minDate?: string
  maxDate?: string
  size?: "sm" | "default"
  fromLabel?: string
  toLabel?: string
  className?: string
  showLabels?: boolean
}

const SIZE_CLASS = {
  sm: "h-7 text-xs px-2",
  default: "h-9 text-13 px-3",
}

function DateRangeFilter({
  from,
  to,
  onFromChange,
  onToChange,
  minDate,
  maxDate,
  size = "default",
  fromLabel = "Desde",
  toLabel = "Hasta",
  className,
  showLabels = false,
}: DateRangeFilterProps) {
  // Estándar: grid de 2 columnas fijas (nunca flex+separador, que rompía el
  // layout en mobile) — cada input ocupa su celda al 100%, sin desbordes.
  const inputClass = cn(SIZE_CLASS[size], "w-full min-w-0")
  const labelClass = "text-2xs font-medium text-muted-foreground block mb-1"
  const visibleFrom = fromLabel.length > 12 ? "Desde" : fromLabel
  const visibleTo = toLabel.length > 12 ? "Hasta" : toLabel

  return (
    <div className={cn("grid grid-cols-2 gap-2 w-full sm:w-auto", className)}>
      <div className="min-w-0">
        {showLabels && <label className={labelClass}>{visibleFrom}</label>}
        <Input
          type="date"
          aria-label={fromLabel}
          value={from}
          max={to || maxDate}
          min={minDate}
          placeholder="dd/mm/aaaa"
          onChange={(e) => onFromChange(e.target.value)}
          className={inputClass}
        />
      </div>
      <div className="min-w-0">
        {showLabels && <label className={labelClass}>{visibleTo}</label>}
        <Input
          type="date"
          aria-label={toLabel}
          value={to}
          min={from || minDate}
          max={maxDate}
          placeholder="dd/mm/aaaa"
          onChange={(e) => onToChange(e.target.value)}
          className={inputClass}
        />
      </div>
    </div>
  )
}

export { DateRangeFilter }
export type { DateRangeFilterProps }
