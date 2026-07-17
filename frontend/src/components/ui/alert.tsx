import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const alertVariants = cva(
  "relative w-full rounded-lg border px-4 py-3 text-sm grid has-[>svg]:grid-cols-[calc(var(--spacing)*4)_1fr] grid-cols-[0_1fr] has-[>svg]:gap-x-3 gap-y-0.5 items-start [&>svg]:size-4 [&>svg]:translate-y-0.5 [&>svg]:text-current",
  {
    variants: {
      variant: {
        default:
          "bg-foreground text-background border-foreground/20",
        destructive:
          "bg-destructive/10 text-destructive border-destructive/30",
        // Success uses the institutional forest green token #1FB107.
        // Soft tint for the surface, full token for text/border on light;
        // mirror inverted for dark mode legibility.
        success:
          "bg-brand-green/12 text-brand-green border-brand-green/40",
        warning:
          "bg-warning/10 text-warning border-warning/30",
        info:
          "bg-primary text-primary-foreground border-primary/80",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Alert({ className, variant, ...props }: React.HTMLAttributes<HTMLDivElement> & VariantProps<typeof alertVariants>) {
  return <div role="alert" data-slot="alert" className={cn(alertVariants({ variant }), className)} {...props} />
}

function AlertTitle({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div data-slot="alert-title" className={cn("col-start-2 font-semibold leading-none tracking-tight", className)} {...props} />
}

function AlertDescription({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div data-slot="alert-description" className={cn("col-start-2 text-sm opacity-90 [&_p]:leading-relaxed", className)} {...props} />
}

export { Alert, AlertTitle, AlertDescription }
