"use client";

import { useEffect, useState } from "react";
import { Bell, FileText, AlertCircle, UserRound, Plug, Inbox, Loader2, Clock, Mail, MailOpen, Check } from "lucide-react";
import { useApi, getErrorMessage } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";
import api from "@/lib/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/composed/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { TableCell, TableRow } from "@/components/ui/table";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select, SelectOption } from "@/components/ui/select";
import { formatInProjectTz } from "@/lib/datetime";
import { Loading } from "@/components/ui/loading";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { FloatingSaveBar } from "../_lib/save-bar";
import { NotificacionesTab } from "../_components/NotificacionesTab";

interface ReportSchedule {
  unit: "daily" | "weekly" | "monthly" | "yearly";
  hour: number;
  minute: number;
  days_of_week?: number[] | null;
  day_of_month?: number | null;
  month?: number | null;
}

interface ChannelDelivery {
  channel: string;
  status: string;
  recipients: number;
  target: string | null;
  error_message: string | null;
}

interface NotificationTrigger {
  id: string;
  event: string;
  created_at: string;
  channels: ChannelDelivery[];
  summary: string | null;
  own_log_id: string | null;
  own_read_at: string | null;
}

interface NotificationsPage {
  items: NotificationTrigger[];
  total: number;
  page: number;
  page_size: number;
}

const CHANNEL_LABEL: Record<string, string> = {
  email: "Correo",
  in_app: "En la app",
};

const EVENT_META: Record<string, { label: string; icon: typeof FileText }> = {
  doc_ready: { label: "Documento procesado", icon: FileText },
  doc_error: { label: "Error procesando documento", icon: AlertCircle },
  escalation: { label: "Chat escalado a humano", icon: UserRound },
  provider_down: { label: "Proveedor IA caído", icon: Plug },
  unanswered_digest: { label: "Resumen diario", icon: Inbox },
  rate_limit_threshold: { label: "Límite de solicitudes cerca del máximo", icon: AlertCircle },
  service_down: { label: "Servicio degradado", icon: AlertCircle },
};

const STATUS_LABEL: Record<string, string> = {
  sent: "Enviada",
  failed: "Falló",
  pending: "Pendiente",
};

const UNIT_LABELS: Record<ReportSchedule["unit"], string> = {
  daily: "Diario",
  weekly: "Semanal",
  monthly: "Mensual",
  yearly: "Anual",
};

// weekday() de Python: lunes=0 … domingo=6
const WEEKDAY_LABELS = ["L", "M", "X", "J", "V", "S", "D"];
const MONTH_LABELS = [
  "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
  "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
];

const HOURS = Array.from({ length: 24 }, (_, h) => h);
const MINUTES = [0, 15, 30, 45];
const DAYS_OF_MONTH = Array.from({ length: 31 }, (_, i) => i + 1);

const DEFAULT_SCHEDULE: ReportSchedule = {
  unit: "daily", hour: 8, minute: 0, days_of_week: [], day_of_month: null, month: null,
};

function fmtDateTime(iso: string) {
  return formatInProjectTz(iso, {
    day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function humanizeNext(s: ReportSchedule): string {
  if (s.unit === "daily") return "Todos los días";
  if (s.unit === "weekly") {
    const ds = (s.days_of_week ?? []).slice().sort().map((d) => WEEKDAY_LABELS[d] ?? "?").join(", ");
    return ds.length ? `Los ${ds}` : "Ningún día seleccionado";
  }
  if (s.unit === "monthly") return `El día ${s.day_of_month ?? "N/A"} de cada mes`;
  if (s.unit === "yearly") return `El ${s.day_of_month ?? "N/A"} de ${MONTH_LABELS[(s.month ?? 1) - 1] ?? ""}`;
  return "";
}

export default function NotificacionesHistorialPage() {
  const { toast } = useToast();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) }).toString();
  const { data, loading, setData } = useApi<NotificationsPage>(`/notifications?${query}`);
  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const unreadOwnCount = items.filter((i) => i.own_log_id && !i.own_read_at).length;

  async function markTriggerRead(trigger: NotificationTrigger) {
    if (!trigger.own_log_id || trigger.own_read_at) return;
    try {
      await api.post(`/notifications/inbox/${trigger.own_log_id}/read`);
      setData((prev) => prev ? {
        ...prev,
        items: prev.items.map((i) =>
          i.id === trigger.id ? { ...i, own_read_at: new Date().toISOString() } : i
        ),
      } : prev);
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo marcar como leída.") });
    }
  }

  async function markAllTriggersRead() {
    try {
      await api.post("/notifications/inbox/mark-all-read");
      setData((prev) => prev ? {
        ...prev,
        items: prev.items.map((i) => i.own_log_id ? { ...i, own_read_at: i.own_read_at ?? new Date().toISOString() } : i),
      } : prev);
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo marcar todas como leídas.") });
    }
  }

  const { data: scheduleData, loading: loadingSchedule } =
    useApi<ReportSchedule>("/notifications/report-schedule");
  const [draft, setDraft] = useState<ReportSchedule>(DEFAULT_SCHEDULE);
  const [savedDraft, setSavedDraft] = useState<ReportSchedule | null>(null);
  const [saving, setSaving] = useState(false);

  // Toggle global de correos: refleja si AL MENOS una regla email está
  // habilitada. Activarlo habilita el canal email para todos los eventos;
  // desactivarlo lo apaga para todos (el canal in-app queda intacto).
  const { data: rulesData, loading: loadingRules } = useApi<{ email_enabled: boolean; smtp_configured: boolean }>(
    "/notifications/rules/email/status",
  );
  const [emailEnabled, setEmailEnabled] = useState(false);
  const [togglingEmail, setTogglingEmail] = useState(false);

  useEffect(() => {
    if (rulesData) setEmailEnabled(rulesData.email_enabled);
  }, [rulesData]);

  async function toggleEmail(next: boolean) {
    setTogglingEmail(true);
    try {
      await api.put("/notifications/rules/email/toggle", { enabled: next });
      setEmailEnabled(next);
      toast({ type: "success", message: next ? "Correos activados." : "Correos desactivados." });
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo cambiar el estado de los correos.") });
    } finally {
      setTogglingEmail(false);
    }
  }

  useEffect(() => {
    if (scheduleData) {
      setDraft(scheduleData);
      setSavedDraft(scheduleData);
    }
  }, [scheduleData]);

  const dirty = !!savedDraft && JSON.stringify(draft) !== JSON.stringify(savedDraft);

  function toggleDay(d: number) {
    setDraft((prev) => {
      const set = new Set(prev.days_of_week ?? []);
      if (set.has(d)) set.delete(d); else set.add(d);
      return { ...prev, days_of_week: Array.from(set).sort((a, b) => a - b) };
    });
  }

  async function saveSchedule() {
    const payload: ReportSchedule = { ...draft };
    if (payload.unit !== "weekly") payload.days_of_week = [];
    if (payload.unit !== "monthly" && payload.unit !== "yearly") payload.day_of_month = null;
    if (payload.unit !== "yearly") payload.month = null;

    if (payload.unit === "weekly" && (payload.days_of_week ?? []).length === 0) {
      toast({ type: "error", message: "Seleccione al menos un día de la semana." });
      return;
    }

    setSaving(true);
    try {
      await api.put<ReportSchedule>("/notifications/report-schedule", payload);
      toast({ type: "success", message: "Programación del reporte guardada." });
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo guardar la programación.") });
    } finally {
      setSaving(false);
      setSavedDraft(payload);
    }
  }

  return (
    <div className="space-y-4">
      <PageHeader title="Notificaciones" icon={Bell} tip="Historial de alertas, programación del reporte de preguntas sin responder y envío por correo." />

      <Tabs defaultValue="historial">
        <TabsList>
          <TabsTrigger value="historial">Historial</TabsTrigger>
          <TabsTrigger value="programacion">Programación</TabsTrigger>
          <TabsTrigger value="eventos">Eventos</TabsTrigger>
        </TabsList>

        <TabsContent value="historial">
          {unreadOwnCount > 0 && (
            <div className="flex justify-end mb-2">
              <Button variant="outline" size="sm" onClick={markAllTriggersRead} className="gap-1.5">
                <Check className="w-3.5 h-3.5" /> Marcar todas ({unreadOwnCount})
              </Button>
            </div>
          )}
          <DataTable
            loading={loading}
            empty={
              <EmptyState icon={Bell} title="Sin notificaciones" description="Todavía no se ha enviado ninguna notificación." className="py-16" />
            }
            pagination={{ page, pageSize, total, onPageChange: setPage, onPageSizeChange: (n) => { setPageSize(n); setPage(1); }, itemLabel: "notificaciones" }}
            columns={[
              { id: "evento", header: "Evento" },
              { id: "canales", header: "Canales", hideBelow: "md" },
              { id: "estado", header: "Estado", className: "w-28" },
              { id: "fecha", header: "Fecha", className: "w-44 hidden sm:table-cell", hideBelow: "sm" },
              { id: "leida", header: "", className: "w-10" },
            ]}
            data={items}
            rowKey={(item) => item.id}
            renderRow={(item) => {
              const meta = EVENT_META[item.event] ?? { label: item.event, icon: Bell };
              const Icon = meta.icon;
              const anyFailed = item.channels.some((c) => c.status === "failed");
              return (
                <TableRow>
                  <TableCell>
                    <div className="flex items-center gap-2 min-w-0">
                      <div className="w-7 h-7 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0" title={meta.label}>
                        <Icon className="w-3.5 h-3.5" />
                      </div>
                      <span className="truncate">{item.summary || meta.label}</span>
                    </div>
                  </TableCell>
                  <TableCell className="hidden md:table-cell">
                    <div className="flex flex-wrap items-center gap-1.5">
                      {item.channels.map((c) => (
                        <Badge
                          key={c.channel}
                          variant={c.status === "failed" ? "destructive" : "muted"}
                          size="xs"
                          title={
                            c.channel === "email"
                              ? (c.target ?? undefined)
                              : `${c.recipients} ${c.recipients === 1 ? "destinatario" : "destinatarios"}`
                          }
                        >
                          {CHANNEL_LABEL[c.channel] ?? c.channel}
                          {c.channel === "in_app" && c.recipients > 1 ? ` (${c.recipients})` : ""}
                        </Badge>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={anyFailed ? "destructive" : "success"} size="xs">
                      {anyFailed ? STATUS_LABEL.failed : STATUS_LABEL.sent}
                    </Badge>
                  </TableCell>
                  <TableCell className="hidden sm:table-cell">
                    <span className="text-muted-foreground whitespace-nowrap tabular-nums">{fmtDateTime(item.created_at)}</span>
                  </TableCell>
                  <TableCell>
                    {item.own_log_id && !item.own_read_at && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-muted-foreground hover:text-primary"
                        title="Marcar como leída"
                        aria-label="Marcar como leída"
                        onClick={() => markTriggerRead(item)}
                      >
                        <Check className="w-3.5 h-3.5" />
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              );
            }}
          />
        </TabsContent>

        <TabsContent value="programacion">
          {loadingSchedule ? (
            <Loading title="Programación del reporte" />
          ) : (
          <>
          <Card>
            <CardHeader className="pb-4 border-b">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0">
                  <Clock className="w-4 h-4" />
                </div>
                <div>
                  <CardTitle className="text-15 font-semibold">Programación del reporte</CardTitle>
                  <CardDescription>Cuándo se genera el reporte de preguntas sin responder</CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent className="pt-4 space-y-4">
              <>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  <div className="space-y-1.5">
                    <Label className="text-2xs font-semibold text-muted-foreground uppercase tracking-wide">Frecuencia</Label>
                    <Select
                      value={draft.unit}
                      onChange={(e) => setDraft((p) => ({ ...p, unit: e.target.value as ReportSchedule["unit"] }))}
                    >
                      {(Object.keys(UNIT_LABELS) as ReportSchedule["unit"][]).map((u) => (
                        <SelectOption key={u} value={u}>{UNIT_LABELS[u]}</SelectOption>
                      ))}
                    </Select>
                    {draft.unit !== "weekly" && (
                      <p className="text-2xs text-muted-foreground">Elegí &quot;Semanal&quot; para escoger días específicos de envío.</p>
                    )}
                  </div>

                  {draft.unit === "weekly" && (
                    <div className="space-y-1.5 sm:col-span-2 lg:col-span-2">
                      <Label className="text-2xs font-semibold text-muted-foreground uppercase tracking-wide">Días de la semana</Label>
                      <div className="flex flex-wrap gap-1.5">
                        {WEEKDAY_LABELS.map((lbl, idx) => {
                          const active = (draft.days_of_week ?? []).includes(idx);
                          return (
                            <button
                              key={idx}
                              type="button"
                              onClick={() => toggleDay(idx)}
                              className={`h-8 w-8 rounded-lg border text-13 font-medium transition-colors ${
                                active
                                  ? "bg-primary text-primary-foreground border-primary"
                                  : "bg-background border-border text-muted-foreground hover:bg-muted"
                              }`}
                            >
                              {lbl}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {draft.unit === "monthly" && (
                    <div className="space-y-1.5">
                      <Label className="text-2xs font-semibold text-muted-foreground uppercase tracking-wide">Día del mes</Label>
                      <Select
                        value={String(draft.day_of_month ?? 1)}
                        onChange={(e) => setDraft((p) => ({ ...p, day_of_month: Number(e.target.value) }))}
                      >
                        {DAYS_OF_MONTH.map((d) => (
                          <SelectOption key={d} value={String(d)}>{d}</SelectOption>
                        ))}
                      </Select>
                    </div>
                  )}

                  {draft.unit === "yearly" && (
                    <>
                      <div className="space-y-1.5">
                        <Label className="text-2xs font-semibold text-muted-foreground uppercase tracking-wide">Mes</Label>
                        <Select
                          value={String(draft.month ?? 1)}
                          onChange={(e) => setDraft((p) => ({ ...p, month: Number(e.target.value) }))}
                        >
                          {MONTH_LABELS.map((m, i) => (
                            <SelectOption key={i + 1} value={String(i + 1)}>{m}</SelectOption>
                          ))}
                        </Select>
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-2xs font-semibold text-muted-foreground uppercase tracking-wide">Día</Label>
                        <Select
                          value={String(draft.day_of_month ?? 1)}
                          onChange={(e) => setDraft((p) => ({ ...p, day_of_month: Number(e.target.value) }))}
                        >
                          {DAYS_OF_MONTH.map((d) => (
                            <SelectOption key={d} value={String(d)}>{d}</SelectOption>
                          ))}
                        </Select>
                      </div>
                    </>
                  )}

                  <div className="space-y-1.5">
                    <Label className="text-2xs font-semibold text-muted-foreground uppercase tracking-wide">Hora</Label>
                    <Select
                      value={String(draft.hour)}
                      onChange={(e) => setDraft((p) => ({ ...p, hour: Number(e.target.value) }))}
                    >
                      {HOURS.map((h) => (
                        <SelectOption key={h} value={String(h)}>{String(h).padStart(2, "0")}:00</SelectOption>
                      ))}
                    </Select>
                  </div>

                  <div className="space-y-1.5">
                    <Label className="text-2xs font-semibold text-muted-foreground uppercase tracking-wide">Minuto</Label>
                    <Select
                      value={String(draft.minute)}
                      onChange={(e) => setDraft((p) => ({ ...p, minute: Number(e.target.value) }))}
                    >
                      {MINUTES.map((m) => (
                        <SelectOption key={m} value={String(m)}>{String(m).padStart(2, "0")}</SelectOption>
                      ))}
                    </Select>
                  </div>
                </div>

                <div className="flex items-center justify-between gap-3 rounded-lg border bg-card px-4 py-3">
                  <p className="text-2xs text-muted-foreground">
                    Envío: <span className="font-medium text-foreground">{humanizeNext(draft)}</span>
                    {" a las "}
                    <span className="font-mono text-foreground">{String(draft.hour).padStart(2, "0")}:{String(draft.minute).padStart(2, "0")} (El Salvador)</span>
                  </p>
                </div>
              </>
            </CardContent>
          </Card>
          <FloatingSaveBar dirty={dirty} saving={saving} onSave={saveSchedule} />
          </>
          )}
        </TabsContent>

        <TabsContent value="eventos">
          <Card className="mb-4">
            <CardContent className="pt-4">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-3 min-w-0">
                  <div className="w-9 h-9 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0">
                    {emailEnabled ? <MailOpen className="w-4 h-4" /> : <Mail className="w-4 h-4" />}
                  </div>
                  <div className="min-w-0">
                    <CardTitle className="text-15 font-semibold">Correos</CardTitle>
                    <CardDescription>
                      {emailEnabled
                        ? "Los administradores reciben estas alertas por correo electrónico."
                        : "Las alertas solo se muestran en la campana."}
                    </CardDescription>
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {loadingRules ? (
                    <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
                  ) : (
                    <Switch
                      checked={emailEnabled}
                      disabled={togglingEmail}
                      onCheckedChange={toggleEmail}
                      aria-label="Activar correos"
                    />
                  )}
                </div>
              </div>
              {emailEnabled && rulesData && !rulesData.smtp_configured && (
                <Alert variant="warning" className="mt-3">
                  <AlertDescription>
                    El canal de correo está activado, pero el servidor no tiene SMTP configurado. Los correos no se enviarán hasta configurarlo.
                  </AlertDescription>
                </Alert>
              )}
            </CardContent>
          </Card>
          <NotificacionesTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
