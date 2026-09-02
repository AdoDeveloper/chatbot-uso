"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { HelpTip } from "./help-tip";

interface ParamFieldProps {
  label: string;
  hint?: React.ReactNode;
  error?: string;
  required?: boolean;
  help?: {
    title?: string;
    description: React.ReactNode;
    example?: React.ReactNode;
    learnMoreHref?: string;
  };
  children: React.ReactNode;
  /** Valor opcional mostrado junto al label, ej. el valor actual del slider */
  valueBadge?: React.ReactNode;
  className?: string;
  htmlFor?: string;
}

/**
 * Wrapper estándar para inputs de configuración/formularios.
 * Garantiza que cada parámetro editable de la app tenga: label + badge de valor
 * opcional + HelpTip opcional + texto de ayuda opcional + error inline.
 *
 * Se usa en todo lugar donde se edite configuración, para que el usuario
 * nunca enfrente un input sin saber qué hace.
 */
export function ParamField({
  label,
  hint,
  error,
  required,
  help,
  children,
  valueBadge,
  className,
  htmlFor,
}: ParamFieldProps) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <label
            htmlFor={htmlFor}
            className="text-xs font-medium text-foreground"
          >
            {label}
            {required && <span className="ml-0.5 text-destructive">*</span>}
          </label>
          {help && (
            <HelpTip
              title={help.title ?? label}
              description={help.description}
              example={help.example}
              learnMoreHref={help.learnMoreHref}
              side="top"
              align="start"
            />
          )}
        </div>
        {valueBadge !== undefined && (
          <span className="text-xs font-semibold tabular-nums text-primary">
            {valueBadge}
          </span>
        )}
      </div>

      {children}

      {error ? (
        <p className="text-xs text-destructive">{error}</p>
      ) : hint ? (
        <p className="text-xs text-muted-foreground leading-snug">{hint}</p>
      ) : null}
    </div>
  );
}
