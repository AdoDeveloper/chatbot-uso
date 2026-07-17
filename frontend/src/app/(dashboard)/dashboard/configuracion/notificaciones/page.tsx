"use client";

import { useEffect, useState } from "react";
import { Bell, FileText, AlertCircle, UserRound, Plug, Inbox, Loader2, Clock, Mail, MailOpen } from "lucide-react";
import { useApi, getErrorMessage } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";
import api from "@/lib/api";
import { DataTable } from "@/components/composed/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { TableCell, TableRow } from "@/components/ui/table";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectOption } from "@/components/ui/select";
import { formatInProjectTz } from "@/lib/datetime";
import { Loading } from "@/components/ui/loading";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { NotificacionesTab } from "../_components/NotificacionesTab";

interface ReportSchedule {
  unit: "daily" | "weekly" | "monthly" | "yearly";
  hour: number;
  minute: number;
  days_of_week?: number[] | null;
  day_of_month?: number | null;
  month?: number | null;
}

interface NotificationLogItem {
  id: string;
  event: string;
  channel: string;
  target: string | null;
  status: string;
  error_message: string | null;
  created_at: string;
  read_at: string | null;
}

interface NotificationsPage {
  items: NotificationLogItem[];
  total: number;
  page: number;
  page_size: number;
}

const EVENT_META: Record<string, { label: string; icon: typeof FileText }> = {
  doc_ready: { label: "Documento procesado", icon: FileText },
  doc_error: { label: "Error procesando documento", icon: AlertCircle },
  escalation: { label: "Chat escalado a humano", icon: UserRound },
  provider_down: { label: "Proveedor IA caído", icon: Plug },
  unanswered_daily: { label: "Resumen diario", icon: Inbox },
};

const STATUS_BADGE: Record<string, string> = {
  sent: "bg-success/10 text-success",
  failed: "bg-destructive/10 text-destructive",
  pending: "bg-muted text-muted-foreground",
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
  if (s.unit === "monthly") return `El día ${s.day_of_month ?? "—"} de cada mes`;
  if (s.unit === "yearly") return `El ${s.day_of_month ?? "—"} de ${MONTH_LABELS[(s.month ?? 1) - 1] ?? ""}`;
  return "";
}

export default function NotificacionesHistorialPage() {
  const { toast } = useToast();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) }).toString();
  const { data, loading } = useApi<NotificationsPage>(`/notifications?${query}`);
  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  const { data: scheduleData, loading: loadingSchedule } =
    useApi<ReportSchedule>("/notifications/report-schedule");
  const [draft, setDraft] = useState<ReportSchedule>(DEFAULT_SCHEDULE);
  const [saving, setSaving] = useState(false);

  // Toggle global de correos: refleja si AL MENOS una regla email está
  // habilitada. Activarlo habilita el canal email para todos los eventos;
  // desactivarlo lo apaga para todos (el canal in-app queda intacto).
  const { data: rulesData, loading: loadingRules } = useApi<{ email_enabled: boolean }>(
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
    if (scheduleData) setDraft(scheduleData);
  }, [scheduleData]);

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
          <DataTable
            loading={loading}
            empty={
              <EmptyState icon={Bell} title="Sin notificaciones" description="Todavía no se ha enviado ninguna notificación." className="py-16" />
            }
            pagination={{ page, pageSize, total, onPageChange: setPage, onPageSizeChange: (n) => { setPageSize(n); setPage(1); }, itemLabel: "notificaciones" }}
            columns={[
              { id: "evento", header: "Evento" },
              { id: "destino", header: "Destino", hideBelow: "md" },
              { id: "estado", header: "Estado", className: "w-28" },
              { id: "fecha", header: "Fecha", className: "w-44 hidden sm:table-cell", hideBelow: "sm" },
            ]}
            data={items}
            rowKey={(item) => item.id}
            renderRow={(item) => {
              const meta = EVENT_META[item.event] ?? { label: item.event, icon: Bell };
              const Icon = meta.icon;
              return (
                <TableRow>
                  <TableCell>
                    <div className="flex items-center gap-2 min-w-0">
                      <div className="w-7 h-7 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0">
                        <Icon className="w-3.5 h-3.5" />
                      </div>
                      <span className="truncate">{meta.label}</span>
                    </div>
                  </TableCell>
                  <TableCell className="hidden md:table-cell">
                    <span className="text-muted-foreground truncate">{item.target ?? "—"}</span>
                  </TableCell>
                  <TableCell>
                    <span className={`text-2xs px-1.5 py-0.5 rounded-full whitespace-nowrap ${STATUS_BADGE[item.status] ?? "bg-muted text-muted-foreground"}`}>
                      {STATUS_LABEL[item.status] ?? item.status}
                    </span>
                  </TableCell>
                  <TableCell className="hidden sm:table-cell">
                    <span className="text-muted-foreground whitespace-nowrap tabular-nums">{fmtDateTime(item.created_at)}</span>
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
                  <Button size="sm" onClick={saveSchedule} disabled={saving} className="gap-1.5 shrink-0">
                    {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Clock className="w-3.5 h-3.5" />}
                    Guardar
                  </Button>
                </div>
              </>
            </CardContent>
          </Card>
          )}
        </TabsContent>

        <TabsContent value="correos">
          <Card>
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
            </CardContent>
          </Card>
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
            </CardContent>
          </Card>
          <NotificacionesTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
