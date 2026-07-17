"use client";

import * as React from "react";
import { HelpCircle } from "lucide-react";
import { cn } from "@/lib/utils";

interface HelpTipProps {
  title?: string;
  description: React.ReactNode;
  example?: React.ReactNode;
  learnMoreHref?: string;
  learnMoreLabel?: string;
  side?: "top" | "bottom" | "left" | "right";
  align?: "start" | "center" | "end";
  iconSize?: "sm" | "md";
  className?: string;
}

/**
 * Rich contextual help popover. Click the ⓘ icon to open.
 * Supports title + description + optional example + optional "learn more" link.
 * Closes on outside click, Escape key, or when opening another HelpTip.
 */
export function HelpTip({
  title,
  description,
  example,
  learnMoreHref,
  learnMoreLabel = "Ver más",
  side = "top",
  align = "center",
  iconSize = "sm",
  className,
}: HelpTipProps) {
  const [open, setOpen] = React.useState(false);
  const rootRef = React.useRef<HTMLSpanElement>(null);
  const popRef = React.useRef<HTMLDivElement>(null);
  const [shift, setShift] = React.useState(0);

  React.useEffect(() => {
    if (!open) return;
    const handleClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, [open]);

  // El popover se posiciona con CSS puro (left-0/right-0) relativo al botón
  // ⓘ — si el trigger está cerca de un borde de pantalla, un panel de w-72
  // (288px) fácilmente se sale del viewport en mobile. Corregimos midiendo
  // el overflow real tras montar y aplicando un translateX de vuelta a
  // pantalla, igual que en el dropdown de notificaciones.
  React.useLayoutEffect(() => {
    if (!open || !popRef.current) { setShift(0); return; }
    const rect = popRef.current.getBoundingClientRect();
    const margin = 12;
    let delta = 0;
    if (rect.left < margin) delta = margin - rect.left;
    else if (rect.right > window.innerWidth - margin) delta = (window.innerWidth - margin) - rect.right;
    setShift(delta);
  }, [open]);

  const positions: Record<string, string> = {
    "top-start":    "bottom-full left-0 mb-2",
    "top-center":   "bottom-full left-1/2 -translate-x-1/2 mb-2",
    "top-end":      "bottom-full right-0 mb-2",
    "bottom-start": "top-full left-0 mt-2",
    "bottom-center":"top-full left-1/2 -translate-x-1/2 mt-2",
    "bottom-end":   "top-full right-0 mt-2",
    "left-start":   "right-full top-0 mr-2",
    "left-center":  "right-full top-1/2 -translate-y-1/2 mr-2",
    "left-end":     "right-full bottom-0 mr-2",
    "right-start":  "left-full top-0 ml-2",
    "right-center": "left-full top-1/2 -translate-y-1/2 ml-2",
    "right-end":    "left-full bottom-0 ml-2",
  };
  const pos = positions[`${side}-${align}`] ?? positions["top-center"];
  const iconCls = iconSize === "sm" ? "w-3.5 h-3.5" : "w-4 h-4";

  return (
    <span ref={rootRef} className={cn("relative inline-flex items-center", className)}>
      <button
        type="button"
        aria-label="Ayuda"
        aria-expanded={open}
        onClick={(e) => { e.preventDefault(); setOpen((v) => !v); }}
        className="inline-flex items-center justify-center p-2.5 -m-2.5 text-muted-foreground hover:text-foreground focus-visible:text-foreground transition-colors"
      >
        <HelpCircle className={iconCls} strokeWidth={2} />
      </button>

      {open && (
        <div
          ref={popRef}
          role="dialog"
          style={shift ? { transform: `translateX(${shift}px)` } : undefined}
          className={cn(
            "absolute z-50 w-72 max-w-[calc(100vw-1.5rem)] rounded-lg border border-border bg-popover text-popover-foreground shadow-md",
            "animate-in fade-in-0 zoom-in-95 duration-100",
            "p-3 text-left",
            pos
          )}
        >
          {title && (
            <p className="text-xs font-semibold text-foreground mb-1">{title}</p>
          )}
          <div className="text-xs leading-relaxed text-muted-foreground">
            {description}
          </div>
          {example && (
            <div className="mt-2 pt-2 border-t border-border/70">
              <p className="text-3xs font-semibold uppercase tracking-wider text-muted-foreground mb-0.5">
                Ejemplo
              </p>
              <div className="text-xs text-foreground">{example}</div>
            </div>
          )}
          {learnMoreHref && (
            <a
              href={learnMoreHref}
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-block text-xs font-medium text-primary hover:underline"
            >
              {learnMoreLabel} →
            </a>
          )}
        </div>
      )}
    </span>
  );
}
