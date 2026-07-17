import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center rounded-md border font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        destructive: "bg-destructive/8 text-destructive border-destructive/20",
        outline: "text-foreground border-border bg-card",
        success: "bg-success/8 text-success border-success/20",
        warning: "bg-warning/8 text-warning border-warning/20",
        info: "bg-info/8 text-info border-info/20",
        muted: "bg-muted text-muted-foreground border-border",
        lab: "bg-warning/15 text-warning border-warning/30 uppercase tracking-wider font-semibold",
      },
      size: {
        sm: "px-2 py-0.5 text-xs",
        xs: "px-1.5 py-0.5 text-3xs",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "sm",
    },
  }
)

function Badge({
  className,
  variant,
  size,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & VariantProps<typeof badgeVariants>) {
  return (
    <div className={cn(badgeVariants({ variant, size }), className)} {...props} />
  )
}

export { Badge, badgeVariants }
