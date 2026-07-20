"use client";

import { useState } from "react";
import { Loader2, Mail } from "lucide-react";
import api from "@/lib/api";
import { useApi, getErrorMessage } from "@/hooks/use-api";
import type { NotificationRule, NotificationEvent, NotificationChannel } from "@/types";
import { Switch } from "@/components/ui/switch";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { Loading } from "@/components/ui/loading";

const EVENT_LABELS: Record<NotificationEvent, string> = {
  doc_ready: "Documento procesado",
  doc_error: "Error de procesamiento",
  escalation: "Escalamiento activado",
  provider_down: "Proveedor IA caído",
  unanswered_digest: "Preguntas sin respuesta (diario)",
  rate_limit_threshold: "Rate limit cerca del techo (≥80%)",
  service_down: "Servicio degradado (MySQL/Redis/Qdrant)",
};

const ALL_EVENTS: NotificationEvent[] = [
  "doc_ready", "doc_error", "escalation", "provider_down", "unanswered_digest",
  "rate_limit_threshold", "service_down",
];
const ALL_CHANNELS: NotificationChannel[] = ["email"];
const CHANNEL_ICONS: Record<NotificationChannel, React.ElementType> = { email: Mail };
const CHANNEL_LABELS: Record<NotificationChannel, string> = { email: "Email" };

export function NotificacionesTab() {
  const { toast } = useToast();
  const { data: rulesData, loading, setData: setRules } = useApi<NotificationRule[]>("/notifications/rules");
  const rules = rulesData ?? [];
  const [toggling, setToggling] = useState<string | null>(null);

  function getRule(event: NotificationEvent, channel: NotificationChannel) {
    return rules.find((r) => r.event === event && r.channel === channel);
  }

  async function toggle(event: NotificationEvent, channel: NotificationChannel) {
    const rule = getRule(event, channel);
    if (!rule) return;
    const key = `${event}:${channel}`;
    setToggling(key);
    try {
      const { data } = await api.put<NotificationRule>(`/notifications/rules/${rule.id}`, {
        enabled: !rule.enabled,
        target: rule.target,
        config_json: rule.config_json ?? {},
      });
      setRules((prev) => (prev ?? []).map((r) => (r.id === data.id ? data : r)));
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo actualizar la regla de notificación.") });
    } finally { setToggling(null); }
  }

  if (loading) {
    return <Loading />;
  }

  return (
    <Card>
      <div className="overflow-x-auto"><Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-64">Evento</TableHead>
            {ALL_CHANNELS.map((ch) => {
              const Icon = CHANNEL_ICONS[ch];
              return (
                <TableHead key={ch} className="text-center">
                  <div className="flex items-center justify-center gap-1.5">
                    <Icon className="w-3.5 h-3.5" />
                    {CHANNEL_LABELS[ch]}
                  </div>
                </TableHead>
              );
            })}
          </TableRow>
        </TableHeader>
        <TableBody>
          {ALL_EVENTS.map((event) => (
            <TableRow key={event}>
              <TableCell className="text-sm text-foreground">
                {EVENT_LABELS[event]}
              </TableCell>
              {ALL_CHANNELS.map((ch) => {
                const rule = getRule(event, ch);
                const key = `${event}:${ch}`;
                const isToggling = toggling === key;
                return (
                  <TableCell key={ch} className="text-center">
                    <div className="flex justify-center">
                      {isToggling ? (
                        <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
                      ) : (
                        <Switch
                          checked={rule?.enabled ?? false}
                          disabled={!rule}
                          onCheckedChange={() => toggle(event, ch)}
                        />
                      )}
                    </div>
                  </TableCell>
                );
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table></div>
    </Card>
  );
}
