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
  /** Optional value displayed next to the label, e.g. the current slider value */
  valueBadge?: React.ReactNode;
  className?: string;
  htmlFor?: string;
}

/**
 * Standard wrapper for configuration/form inputs.
 * Ensures every editable parameter in the app has: label + optional value badge
 * + optional HelpTip + optional hint text + inline error.
 *
 * Use this everywhere config is edited so the user never faces a bare input
 * without knowing what it does.
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
