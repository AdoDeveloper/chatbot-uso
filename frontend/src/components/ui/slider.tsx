"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

function Slider({
  value,
  onValueChange,
  min = 0,
  max = 100,
  step = 1,
  className,
  disabled,
  ...props
}: Omit<React.ComponentProps<"div">, "onChange"> & {
  value?: number
  onValueChange?: (value: number) => void
  min?: number
  max?: number
  step?: number
  disabled?: boolean
}) {
  const pct = ((value ?? min) - min) / (max - min) * 100

  return (
    <div
      data-slot="slider"
      className={cn("relative flex h-4 w-full touch-none select-none items-center", className)}
      {...props}
    >
      <div className="relative h-1.5 w-full grow overflow-hidden rounded-full bg-primary/20">
        <div className="absolute h-full bg-primary rounded-full" style={{ width: `${pct}%` }} />
      </div>
      <div
        className="pointer-events-none absolute h-4 w-4 rounded-full border border-primary/50 bg-background shadow transition-colors focus-visible:outline-none"
        style={{ left: `calc(${pct}% - 8px)` }}
      />
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value ?? min}
        disabled={disabled}
        onChange={(e) => onValueChange?.(Number(e.target.value))}
        className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
      />
    </div>
  )
}

export { Slider }
