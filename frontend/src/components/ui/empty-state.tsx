import * as React from "react"
import { cn } from "@/lib/utils"

function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ComponentType<{ className?: string }>
  title: string
  description?: string
  action?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center py-10 px-6 text-center", className)}>
      {Icon && (
        <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-muted">
          <Icon className="h-5 w-5 text-muted-foreground" />
        </div>
      )}
      <h3 className="text-13 font-semibold text-foreground">{title}</h3>
      {description && (
        <p className="mt-1 max-w-sm text-[12.5px] text-muted-foreground leading-relaxed">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export { EmptyState }
