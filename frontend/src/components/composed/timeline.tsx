import Link from "next/link";
import {
  Database, Rocket, ShieldAlert, Bell, AlertCircle,
  Trash2, LogIn, FileText, TrendingUp, Circle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";

export type TimelineEventType =
  | "source_ingested" | "source_promoted" | "guardrail_block" | "escalation"
  | "provider_error" | "cache_cleared" | "user_login" | "version_snapshot"
  | "unanswered_spike" | "other";

export interface TimelineEvent {
  id: string;
  type: TimelineEventType;
  title: string;
  detail: string | null;
  created_at: string;
  actor_name: string | null;
  href: string | null;
}

export const TIMELINE_ICON: Record<TimelineEventType, { icon: typeof LogIn; color: string; bg: string; ring: string; label: string }> = {
  source_ingested:  { icon: Database,    color: "text-primary",   bg: "bg-primary/10",   ring: "ring-primary/20",   label: "Fuente" },
  source_promoted:  { icon: Rocket,      color: "text-success",   bg: "bg-success/10",   ring: "ring-success/20",   label: "Publicado" },
  guardrail_block:  { icon: ShieldAlert, color: "text-destructive", bg: "bg-destructive/10", ring: "ring-destructive/20", label: "Bloqueo" },
  escalation:       { icon: Bell,        color: "text-warning",   bg: "bg-warning/10",   ring: "ring-warning/20",   label: "Escalamiento" },
  provider_error:   { icon: AlertCircle, color: "text-destructive", bg: "bg-destructive/10", ring: "ring-destructive/20", label: "Error IA" },
  cache_cleared:    { icon: Trash2,      color: "text-muted-foreground", bg: "bg-muted",   ring: "ring-border",       label: "Caché" },
  user_login:       { icon: LogIn,       color: "text-muted-foreground", bg: "bg-muted",   ring: "ring-border",       label: "Acceso" },
  version_snapshot: { icon: FileText,    color: "text-primary",   bg: "bg-primary/10",   ring: "ring-primary/20",   label: "Versión" },
  unanswered_spike: { icon: TrendingUp,  color: "text-warning",   bg: "bg-warning/10",   ring: "ring-warning/20",   label: "Pico" },
  other:            { icon: Circle,      color: "text-muted-foreground", bg: "bg-muted",   ring: "ring-border",       label: "Evento" },
};

export function TimelineDot({ type, dimmed }: { type: TimelineEventType; dimmed?: boolean }) {
  const meta = TIMELINE_ICON[type];
  const Icon = meta.icon;
  return (
    <div className={cn(
      "relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full ring-4 ring-card",
      meta.bg, meta.ring,
      dimmed && "opacity-60",
    )}>
      <Icon className={cn("h-3.5 w-3.5", meta.color)} />
    </div>
  );
}

function groupByDay(events: TimelineEvent[]): { key: string; label: string; events: TimelineEvent[] }[] {
  const groups: Record<string, TimelineEvent[]> = {};
  for (const ev of events) {
    const d = new Date(ev.created_at);
    const key = d.toISOString().slice(0, 10);
    (groups[key] ??= []).push(ev);
  }
  const fmt = (d: Date) =>
    d.toLocaleDateString("es", { weekday: "long", day: "numeric", month: "long" });
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1);

  return Object.entries(groups)
    .sort((a, b) => (a[0] < b[0] ? 1 : -1))
    .map(([key, evs]) => {
      const d = new Date(key + "T00:00:00");
      let label = fmt(d);
      if (d.getTime() === today.getTime()) label = "Hoy";
      else if (d.getTime() === yesterday.getTime()) label = "Ayer";
      return { key, label: label.charAt(0).toUpperCase() + label.slice(1), events: evs };
    });
}

export function TimelineItem({
  event,
  showActor,
}: {
  event: TimelineEvent;
  showActor?: boolean;
}) {
  const dt = new Date(event.created_at);
  const meta = TIMELINE_ICON[event.type];
  const timeLabel = dt.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });

  const body = (
    <div className="group flex items-start gap-3 rounded-xl border border-transparent px-3 py-2.5 transition-colors hover:border-border hover:bg-muted/40">
      <TimelineDot type={event.type} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <Badge variant="muted" size="xs" className="shrink-0">{meta.label}</Badge>
          <p className="text-13 font-medium text-foreground truncate">
            {event.title}
          </p>
        </div>
        {event.detail && (
          <p className="text-2xs text-muted-foreground mt-1 leading-snug">{event.detail}</p>
        )}
        <div className="mt-1 flex items-center gap-2 text-3xs text-muted-foreground tabular-nums">
          <span>{timeLabel}</span>
          {showActor && event.actor_name && (
            <>
              <span className="h-0.5 w-0.5 rounded-full bg-muted-foreground/50" />
              <span className="truncate">por {event.actor_name}</span>
            </>
          )}
        </div>
      </div>
    </div>
  );

  return (
    <div className={cn("relative", event.href && "cursor-pointer")}>
      {event.href ? (
        <Link href={event.href} className="block rounded-xl focus:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {body}
        </Link>
      ) : (
        body
      )}
    </div>
  );
}

export function TimelineContainer({
  children,
  scrollable,
}: {
  children: React.ReactNode;
  scrollable?: boolean;
}) {
  return (
    <div className={cn("relative", scrollable && "max-h-120 overflow-y-auto pr-1")}>
      <div className="space-y-4">
        {children}
      </div>
    </div>
  );
}

/** Renderiza eventos agrupados por día con separadores de fecha. */
export function TimelineGrouped({
  events,
  showActor,
  scrollable,
}: {
  events: TimelineEvent[];
  showActor?: boolean;
  scrollable?: boolean;
}) {
  const groups = groupByDay(events);
  return (
    <TimelineContainer scrollable={scrollable}>
      {groups.map((g) => (
        <div key={g.key} className="relative">
          {/* Riel vertical continuo detrás de los dots */}
          <div className="absolute left-[15px] top-7 bottom-0 w-px bg-border/70" />
          <p className="mb-1.5 px-3 text-3xs font-semibold uppercase tracking-wider text-muted-foreground">
            {g.label}
          </p>
          <div className="space-y-0.5">
            {g.events.map((ev) => (
              <TimelineItem key={ev.id} event={ev} showActor={showActor} />
            ))}
          </div>
        </div>
      ))}
    </TimelineContainer>
  );
}
