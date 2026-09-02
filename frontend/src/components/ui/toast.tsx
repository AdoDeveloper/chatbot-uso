"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle, XCircle, Info, X, AlertTriangle } from "lucide-react";

type ToastType = "success" | "error" | "info" | "warning";

interface Toast {
  id: string;
  type: ToastType;
  title: string;
  message?: string;
}

interface ToastOptions {
  message: string;
  title?: string;
  type?: ToastType;
  duration?: number;
}

interface ConfirmOptions {
  title: string;
  message?: string;
  confirmText?: string;
  cancelText?: string;
  variant?: "danger" | "default";
}

interface ToastContextValue {
  toast: (options: ToastOptions) => void;
  confirm: (options: ConfirmOptions) => Promise<boolean>;
}

const ToastContext = createContext<ToastContextValue>({
  toast: () => {},
  confirm: () => Promise.resolve(false),
});

const DEFAULT_TITLES: Record<ToastType, string> = {
  success: "Exitoso",
  error: "Error",
  info: "Información",
  warning: "Advertencia",
};

const ICON_BG: Record<ToastType, string> = {
  info: "bg-info/10",
  success: "bg-success/10",
  warning: "bg-warning/10",
  error: "bg-destructive/10",
};

const ICON_COLOR: Record<ToastType, string> = {
  info: "text-info",
  success: "text-success",
  warning: "text-warning",
  error: "text-destructive",
};

const ICONS: Record<ToastType, React.ElementType> = {
  success: CheckCircle,
  error: XCircle,
  info: Info,
  warning: AlertTriangle,
};

const BORDER_COLOR: Record<ToastType, string> = {
  info: "border-l-info",
  success: "border-l-success",
  warning: "border-l-warning",
  error: "border-l-destructive",
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [dialog, setDialog] = useState<(ConfirmOptions & { resolve: (v: boolean) => void }) | null>(null);
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  useEffect(() => {
    return () => {
      timers.current.forEach((id) => clearTimeout(id));
    };
  }, []);

  const remove = useCallback((id: string) => {
    const timer = timers.current.get(id);
    if (timer !== undefined) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback(({ message, title, type = "info", duration = 4000 }: ToastOptions) => {
    const id = Math.random().toString(36).slice(2);
    setToasts((prev) => [...prev.slice(-4), { id, type, title: title || DEFAULT_TITLES[type], message }]);
    const timer = setTimeout(() => remove(id), duration);
    timers.current.set(id, timer);
  }, [remove]);

  const confirm = useCallback((options: ConfirmOptions): Promise<boolean> => {
    return new Promise((resolve) => {
      // Solo hay un slot de diálogo global: si ya había una confirmación pendiente, se resuelve en false para no dejarla huérfana.
      setDialog((prev) => {
        prev?.resolve(false);
        return { ...options, resolve };
      });
    });
  }, []);

  function handleConfirm(value: boolean) {
    dialog?.resolve(value);
    setDialog(null);
  }

  // Memoizado para no re-renderizar todos los consumidores de useToast() en cada aparición/desaparición de un toast.
  const ctxValue = useMemo(() => ({ toast, confirm }), [toast, confirm]);

  return (
    <ToastContext.Provider value={ctxValue}>
      {children}

      {/* Pila de toasts */}
      <div className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2.5 pointer-events-none">
        {toasts.map((t) => {
          const Icon = ICONS[t.type];
          return (
            <div
              key={t.id}
              className={`pointer-events-auto flex items-start gap-3 pl-4 pr-3 py-3.5 rounded-xl border-l-4 ${BORDER_COLOR[t.type]} bg-card shadow-2xl border border-border max-w-sm animate-in slide-in-from-right-5 duration-300`}
            >
              <div className={`w-8 h-8 rounded-full ${ICON_BG[t.type]} flex items-center justify-center shrink-0 mt-0.5`}>
                <Icon className={`w-4 h-4 ${ICON_COLOR[t.type]}`} strokeWidth={2.5} />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-bold text-card-foreground">{t.title}</p>
                {t.message && <p className="text-13 text-muted-foreground mt-0.5 leading-snug">{t.message}</p>}
              </div>
              <button
                onClick={() => remove(t.id)}
                className="shrink-0 text-muted-foreground hover:text-card-foreground transition-colors mt-0.5"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          );
        })}
      </div>

      {/* Diálogo de confirmación */}
      {dialog && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/50" onClick={() => handleConfirm(false)} />
          <div className="relative bg-card text-card-foreground rounded-xl shadow-2xl w-full max-w-md overflow-hidden animate-in zoom-in-95 duration-200 border border-border">
            <div className="px-6 pt-6 pb-4">
              <div className="flex items-start gap-3">
                <div className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${
                  dialog.variant === "danger" ? "bg-destructive/10" : "bg-primary/10"
                }`}>
                  {dialog.variant === "danger"
                    ? <AlertTriangle className="w-5 h-5 text-destructive" />
                    : <Info className="w-5 h-5 text-primary" />}
                </div>
                <div>
                  <h3 className="text-base font-semibold text-foreground">{dialog.title}</h3>
                  {dialog.message && <p className="text-sm text-muted-foreground mt-1">{dialog.message}</p>}
                </div>
              </div>
            </div>
            <div className="flex justify-end gap-2 px-6 py-4 border-t border-border">
              <button
                onClick={() => handleConfirm(false)}
                className="h-9 px-4 text-sm font-medium text-foreground bg-card border border-border rounded-lg hover:bg-muted transition-colors"
              >
                {dialog.cancelText || "Cancelar"}
              </button>
              <button
                onClick={() => handleConfirm(true)}
                className={`h-9 px-4 text-sm font-medium rounded-lg transition-colors ${
                  dialog.variant === "danger"
                    ? "text-destructive-foreground bg-destructive hover:bg-destructive/90"
                    : "text-primary-foreground bg-primary hover:opacity-90"
                }`}
              >
                {dialog.confirmText || "Confirmar"}
              </button>
            </div>
          </div>
        </div>
      )}
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
