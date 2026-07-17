"use client";

import { type ReactNode } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

type ModalSize = "sm" | "md" | "lg" | "xl" | "2xl" | "3xl";

const SIZE_CLASS: Record<ModalSize, string> = {
  sm: "max-w-sm",
  md: "max-w-md",
  lg: "max-w-lg",
  xl: "max-w-xl",
  "2xl": "max-w-2xl",
  "3xl": "max-w-3xl",
};

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  size?: ModalSize;
  footer?: ReactNode;
  children: ReactNode;
  /**
   * Si se pasa, `children` y `footer` se envuelven en un único `<form>` que
   * llama a este handler al enviarse (típicamente `handleSubmit(onValid)` de
   * react-hook-form). Esto es OBLIGATORIO usar en vez de un `<form>` propio
   * dentro de `children`: internamente `footer` se renderiza en un `<div>`
   * hermano de `children`, no anidado, así que un `<form>` puesto solo en
   * `children` nunca contendría al botón submit del footer — el click no
   * dispara ningún envío (bug real ya visto: el botón no hace nada, sin
   * error ni request). Con esta prop, el propio `<form>` envuelve ambos.
   * Si no necesitas un formulario nativo (usas `onClick` directo en los
   * botones del footer), simplemente omite esta prop.
   */
  onSubmit?: (e: React.FormEvent) => void;
}

export function Modal({ open, onClose, title, subtitle, size = "lg", footer, children, onSubmit }: ModalProps) {
  const hasFooter = !!footer;
  const Wrapper = onSubmit ? "form" : "div";
  const wrapperProps = onSubmit ? { onSubmit } : {};

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose(); }}>
      <DialogContent
        className={
          hasFooter
            ? `${SIZE_CLASS[size]} p-0 flex flex-col gap-0 max-h-[90vh] overflow-hidden`
            : SIZE_CLASS[size]
        }
        hideCloseButton={hasFooter}
      >
        <DialogHeader className={cn(hasFooter && "px-6 py-4 border-b border-border mb-0 shrink-0")}>
          <DialogTitle>{title}</DialogTitle>
          {subtitle && <p className="text-2xs text-muted-foreground">{subtitle}</p>}
        </DialogHeader>
        {hasFooter ? (
          <Wrapper {...wrapperProps} className="contents">
            <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
            <div className="px-6 py-4 border-t border-border flex gap-3 shrink-0 justify-end">
              {footer}
            </div>
          </Wrapper>
        ) : (
          <div className="pb-2">{children}</div>
        )}
      </DialogContent>
    </Dialog>
  );
}
