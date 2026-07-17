import * as React from "react"
import { cn } from "@/lib/utils"

function Progress({
  value = 0,
  max = 100,
  className,
  indicatorClassName,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & {
  value?: number
  max?: number
  indicatorClassName?: string
}) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100))

  return (
    <div
      role="progressbar"
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={max}
      data-slot="progress"
      className={cn("relative h-2 w-full overflow-hidden rounded-full bg-primary/20", className)}
      {...props}
    >
      <div
        className={cn("h-full rounded-full bg-primary transition-all duration-300", indicatorClassName)}
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

export { Progress }
