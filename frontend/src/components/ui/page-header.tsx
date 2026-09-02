import type { LucideIcon } from "lucide-react";
import { HelpTip } from "@/components/ui/help-tip";

interface PageHeaderProps {
  title: string;
  description?: string;
  action?: React.ReactNode;
  badge?: React.ReactNode;
  icon?: LucideIcon;
  /** Tooltip informativo (ⓘ) junto al título - qué es esta vista y para qué sirve. */
  tip?: React.ReactNode;
}

// `description` no se renderiza (el estándar del panel es solo título, sin subtítulo); usar `tip` para contexto adicional.
export function PageHeader({ title, action, badge, icon: Icon, tip }: PageHeaderProps) {
  return (
    <div className="flex items-center justify-between gap-2 mb-6 pb-5 border-b border-border">
      <div className="min-w-0 flex items-center gap-1.5">
        {Icon && (
          <div className="w-7 h-7 flex items-center justify-center shrink-0">
            <Icon className="w-4 h-4 text-primary" strokeWidth={1.8} />
          </div>
        )}
        <div className="min-w-0 flex items-center gap-2 flex-wrap">
          <h1 className="text-lg font-semibold tracking-tight text-foreground leading-tight truncate">
            {title}
          </h1>
          {tip && <HelpTip description={tip} side="bottom" align="start" />}
          {badge}
        </div>
      </div>
      {action && (
        <div className="shrink-0 flex items-center gap-2">{action}</div>
      )}
    </div>
  );
}
