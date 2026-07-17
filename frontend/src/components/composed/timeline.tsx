import Link from "next/link";
import {
  Database, Rocket, ShieldAlert, Bell, AlertCircle,
  Trash2, LogIn, FileText, TrendingUp, Circle,
} from "lucide-react";

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

export const TIMELINE_ICON: Record<TimelineEventType, { icon: typeof LogIn; color: string }> = {
  source_ingested:  { icon: Database,    color: "text-primary" },
  source_promoted:  { icon: Rocket,      color: "text-success" },
  guardrail_block:  { icon: ShieldAlert, color: "text-destructive" },
  escalation:       { icon: Bell,        color: "text-warning" },
  provider_error:   { icon: AlertCircle, color: "text-destructive" },
  cache_cleared:    { icon: Trash2,      color: "text-muted-foreground" },
  user_login:       { icon: LogIn,       color: "text-muted-foreground" },
  version_snapshot: { icon: FileText,    color: "text-primary" },
  unanswered_spike: { icon: TrendingUp,  color: "text-warning" },
  other:            { icon: Circle,      color: "text-muted-foreground" },
};

export function TimelineDot({ type }: { type: TimelineEventType }) {
  const meta = TIMELINE_ICON[type];
  const Icon = meta.icon;
  const colorMap: Record<string, string> = {
    "text-primary": "bg-primary/10",
    "text-success": "bg-success/10",
    "text-destructive": "bg-destructive/10",
    "text-warning": "bg-warning/10",
    "text-muted-foreground": "bg-muted",
  };
  return (
    <div className={`absolute -left-[21px] top-0 h-[18px] w-[18px] rounded-full flex items-center justify-center ${colorMap[meta.color] ?? "bg-muted"} ${meta.color}`}>
      <Icon className="w-2.5 h-2.5" />
    </div>
  );
}

export function TimelineItem({
  event,
  showActor,
  card,
}: {
  event: TimelineEvent;
  showActor?: boolean;
  card?: boolean;
}) {
  const dt = new Date(event.created_at);
  const content = (
    <div className="flex items-start justify-between gap-2">
      <div className="min-w-0">
        {event.href ? (
          <Link href={event.href} className="text-13 font-medium hover:underline">{event.title}</Link>
        ) : (
          <p className="text-13 font-medium">{event.title}</p>
        )}
        {event.detail && <p className="text-2xs text-muted-foreground mt-0.5 truncate">{event.detail}</p>}
      </div>
      <span className="text-3xs tabular-nums text-muted-foreground shrink-0">
        {dt.toLocaleDateString("es", { day: "2-digit", month: "short" })}
        <span className={showActor ? "block" : "block text-right"}>
          {dt.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" })}
        </span>
      </span>
    </div>
  );

  if (card) {
    return (
      <div className="relative">
        <TimelineDot type={event.type} />
        <div className="rounded-lg border border-border bg-card px-3 py-2 hover:bg-muted/30 transition-colors">
          {content}
          {showActor && event.actor_name && (
            <p className="text-3xs text-muted-foreground mt-1">por {event.actor_name}</p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="relative">
      <TimelineDot type={event.type} />
      {content}
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
    <div className={`relative pl-6 space-y-3 ${scrollable ? "max-h-120 overflow-y-auto" : ""}`}>
      <div className="absolute left-[9px] top-0 bottom-0 w-px bg-border" />
      {children}
    </div>
  );
}
