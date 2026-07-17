"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Bell, FileText, AlertCircle, UserRound, Plug, Inbox, Check } from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
  useDropdownMenu,
} from "@/components/ui/dropdown-menu";

// Bell del header con dropdown de notificaciones reales (antes era un dot
// estático). Polling cada 30s, marca como leída al click, link al historial
// completo en /sistema/notificaciones.

interface InboxItem {
  id: string;
  event: string;
  channel: string;
  target: string;
  status: string;
  error_message: string | null;
  created_at: string;
  read_at: string | null;
}

interface InboxResponse {
  unread_count: number;
  items: InboxItem[];
}

const EVENT_META: Record<string, { label: string; icon: typeof FileText; href?: string }> = {
  doc_ready: { label: "Documento procesado", icon: FileText, href: "/dashboard/conocimiento/documentos" },
  doc_error: { label: "Error procesando documento", icon: AlertCircle, href: "/dashboard/conocimiento/documentos" },
  escalation: { label: "Chat escalado a humano", icon: UserRound, href: "/dashboard/conversaciones?status=escalated" },
  provider_down: { label: "Proveedor IA caído", icon: Plug, href: "/dashboard/configuracion/proveedores" },
  service_down: { label: "Servicio degradado", icon: Plug, href: "/dashboard/configuracion/proveedores" },
  rate_limit_threshold: { label: "Cerca del límite de cuotas", icon: AlertCircle, href: "/dashboard/configuracion/cuotas" },
  unanswered_daily: { label: "Resumen diario", icon: Inbox, href: "/dashboard/conversaciones/pendientes" },
};

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "ahora";
  if (m < 60) return `hace ${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `hace ${h}h`;
  const d = Math.floor(h / 24);
  if (d < 7) return `hace ${d}d`;
  return new Date(iso).toLocaleDateString("es");
}

export function NotificationsBell() {
  const [data, setData] = useState<InboxResponse | null>(null);
  const pollingRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const { data } = await api.get<InboxResponse>("/notifications/inbox?limit=10");
        setData(data);
      } catch {
        // 401/403/network — silently ignore. Bell shows no badge.
      }
    }

    load();
    pollingRef.current = setInterval(load, 30000);
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, []);

  async function markRead(id: string) {
    try {
      await api.post(`/notifications/inbox/${id}/read`);
      setData((prev) => prev ? {
        ...prev,
        unread_count: Math.max(0, prev.unread_count - 1),
        items: prev.items.map((i) => i.id === id ? { ...i, read_at: new Date().toISOString() } : i),
      } : prev);
    } catch { /* ignore */ }
  }

  async function markAllRead() {
    try {
      await api.post("/notifications/inbox/mark-all-read");
      setData((prev) => prev ? {
        unread_count: 0,
        items: prev.items.map((i) => ({ ...i, read_at: i.read_at ?? new Date().toISOString() })),
      } : prev);
    } catch { /* ignore */ }
  }

  const unread = data?.unread_count ?? 0;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative h-8 w-8"
          title="Notificaciones"
          aria-label={unread > 0 ? `Notificaciones (${unread} sin leer)` : "Notificaciones"}
        >
          <Bell className="h-3.5 w-3.5" aria-hidden="true" />
          {unread > 0 && (
            <span className="absolute -top-0.5 -right-0.5 min-w-4 h-4 px-1 rounded-full bg-destructive text-destructive-foreground text-[9px] font-bold flex items-center justify-center tabular-nums">
              {unread > 9 ? "9+" : unread}
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-[min(20rem,calc(100vw-1.5rem))] p-0 max-h-[min(37.5rem,80vh)] overflow-hidden flex flex-col">
        <NotificationsPanel data={data} unread={unread} markRead={markRead} markAllRead={markAllRead} />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function NotificationsPanel({
  data, unread, markRead, markAllRead,
}: {
  data: InboxResponse | null;
  unread: number;
  markRead: (id: string) => void;
  markAllRead: () => void;
}) {
  const { setOpen } = useDropdownMenu();

  return (
    <>
      <div className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Notificaciones {unread > 0 && <span className="text-destructive">({unread})</span>}
        </span>
        {unread > 0 && (
          <button
            type="button"
            onClick={markAllRead}
            className="text-2xs text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 rounded"
          >
            Marcar todas
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto">
        {!data || data.items.length === 0 ? (
          <div className="px-3 py-8 text-center">
            <Inbox className="w-6 h-6 mx-auto mb-2 text-muted-foreground/50" />
            <p className="text-xs text-muted-foreground">Sin notificaciones</p>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {data.items.map((item) => {
              const meta = EVENT_META[item.event] ?? { label: item.event, icon: Bell };
              const Icon = meta.icon;
              const itemUnread = !item.read_at;
              const failed = item.status === "failed";
              const content = (
                <div className="flex items-start gap-2 px-3 py-2.5 hover:bg-muted/50 transition-colors">
                  <div className={`mt-0.5 p-1 rounded ${failed ? "bg-destructive/10 text-destructive" : "bg-primary/10 text-primary"}`}>
                    <Icon className="w-3 h-3" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <p className={`text-xs ${itemUnread ? "font-semibold" : "font-normal"} truncate`}>
                        {meta.label}
                      </p>
                      {itemUnread && <span className="w-1.5 h-1.5 rounded-full bg-primary shrink-0" />}
                    </div>
                    <p className="text-3xs text-muted-foreground truncate mt-0.5">
                      {item.channel === "in_app" ? "Notificación en la app" : `Email → ${item.target}`}
                    </p>
                    {failed && item.error_message && (
                      <p className="text-3xs text-destructive truncate mt-0.5">{item.error_message}</p>
                    )}
                    <p className="text-3xs text-muted-foreground mt-0.5">{timeAgo(item.created_at)}</p>
                  </div>
                </div>
              );

              return meta.href ? (
                <Link
                  key={item.id}
                  href={meta.href}
                  onClick={() => { if (itemUnread) markRead(item.id); setOpen(false); }}
                  className="block focus-visible:outline-none focus-visible:bg-muted"
                >
                  {content}
                </Link>
              ) : (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => { if (itemUnread) markRead(item.id); setOpen(false); }}
                  className="w-full text-left focus-visible:outline-none focus-visible:bg-muted"
                >
                  {content}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="border-t border-border px-3 py-2 shrink-0">
        <Link
          href="/dashboard/configuracion/notificaciones"
          onClick={() => setOpen(false)}
          className="flex items-center justify-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <Check className="w-3 h-3" /> Ver configuración
        </Link>
      </div>
    </>
  );
}
