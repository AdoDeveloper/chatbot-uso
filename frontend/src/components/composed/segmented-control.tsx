"use client";

import { cn } from "@/lib/utils";

interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  icon?: React.ComponentType<{ className?: string }>;
}

interface SegmentedControlProps<T extends string> {
  value: T;
  onChange: (value: T) => void;
  options: SegmentedOption<T>[];
  ariaLabel: string;
  /**
   * "thumb": 2-4 opciones excluyentes tipo ambiente/rango de fecha —
   * contenedor con padding y el activo resaltado con fondo + sombra.
   * "chip": filtros de tags/estado — pills independientes, activo en color primary.
   */
  variant?: "thumb" | "chip";
  className?: string;
}

export function SegmentedControl<T extends string>({
  value,
  onChange,
  options,
  ariaLabel,
  variant = "thumb",
  className,
}: SegmentedControlProps<T>) {
  if (variant === "chip") {
    return (
      <div role="group" aria-label={ariaLabel} className={cn("inline-flex items-center gap-1.5 flex-wrap", className)}>
        {options.map(({ value: v, label, icon: Icon }) => (
          <button
            key={v}
            type="button"
            onClick={() => onChange(v)}
            aria-pressed={value === v}
            className={cn(
              "inline-flex items-center gap-1.5 h-7 px-3 rounded-full border text-xs font-medium transition-colors",
              value === v
                ? "bg-primary text-primary-foreground border-primary"
                : "bg-background text-muted-foreground border-border hover:bg-muted-foreground/10 hover:text-foreground"
            )}
          >
            {Icon && <Icon className="w-3.5 h-3.5" />}
            {label}
          </button>
        ))}
      </div>
    );
  }

  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={cn("inline-flex items-center gap-0.5 p-0.5 bg-muted border border-border rounded-lg", className)}
    >
      {options.map(({ value: v, label, icon: Icon }) => (
        <button
          key={v}
          type="button"
          onClick={() => onChange(v)}
          aria-pressed={value === v}
          className={cn(
            "flex items-center gap-1.5 px-3 py-1 rounded-md text-13 font-medium transition-all",
            value === v
              ? "bg-background shadow-sm text-foreground"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          {Icon && <Icon className="w-3.5 h-3.5" />}
          {label}
        </button>
      ))}
    </div>
  );
}
