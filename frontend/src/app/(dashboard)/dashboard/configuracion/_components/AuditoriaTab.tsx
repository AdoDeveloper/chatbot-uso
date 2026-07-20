"use client";

import { useMemo, useState } from "react";
import { Search, ShieldCheck, Download, Eye } from "lucide-react";
import api from "@/lib/api";
import { useApi } from "@/hooks/use-api";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from "@/components/ui/dropdown-menu";
import type { AuditLog } from "@/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DataTable, type Column } from "@/components/composed/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { DateRangeFilter } from "@/components/composed/date-range-filter";
import { Loading } from "@/components/ui/loading";
import { Modal } from "@/components/composed/modal";
import { formatInProjectTz } from "@/lib/datetime";

function relativeTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const min = Math.floor(diff / 60_000);
  if (min < 1) return "hace un momento";
  if (min < 60) return `hace ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `hace ${h}h`;
  const d = new Date(iso);
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (formatInProjectTz(d, { day: "2-digit", month: "2-digit", year: "numeric" }) ===
      formatInProjectTz(yesterday, { day: "2-digit", month: "2-digit", year: "numeric" })) {
    return `ayer ${formatInProjectTz(d, { hour: "2-digit", minute: "2-digit" })}`;
  }
  return formatInProjectTz(d, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

function actorInitials(name: string) {
  return name
    .split(" ")
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
}

const ACTOR_COLORS = [
  "bg-primary/10 text-primary",
  "bg-brand-teal/10 text-brand-teal",
  "bg-warning/10 text-warning",
  "bg-brand-green/10 text-brand-green",
  "bg-brand-cornflower/15 text-brand-steel",
];

function actorColor(name: string) {
  const h = name.split("").reduce((a, c) => a + c.charCodeAt(0), 0);
  return ACTOR_COLORS[h % ACTOR_COLORS.length];
}

const RESOURCE_TYPES = [
  { value: "", label: "Todos los recursos" },
  { value: "source", label: "Fuentes" },
  { value: "user", label: "Usuarios" },
  { value: "provider", label: "Proveedores" },
  { value: "settings", label: "Configuración" },
  { value: "faq", label: "FAQ" },
  { value: "widget", label: "Widget" },
  { value: "ip", label: "IP / Seguridad" },
  { value: "llm_provider", label: "LLM provider" },
];

interface ActorOption { id: string; name: string; }

export function AuditoriaTab() {
  const [search, setSearch] = useState("");
  const [resourceType, setResourceType] = useState("");
  const [actorId, setActorId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [detail, setDetail] = useState<AuditLog | null>(null);

  const { data: actorsData } = useApi<ActorOption[]>("/audit/actors");
  const actors = actorsData ?? [];

  const logsQuery = useMemo(() => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
      sort_by: "created_at",
      sort_dir: "desc",
    });
    if (search.trim()) params.set("action", search.trim());
    if (resourceType) params.set("resource_type", resourceType);
    if (actorId) params.set("actor_id", actorId);
    if (dateFrom) params.set("date_from", new Date(dateFrom).toISOString());
    if (dateTo) params.set("date_to", new Date(dateTo + "T23:59:59").toISOString());
    return params.toString();
  }, [search, resourceType, actorId, dateFrom, dateTo, page, pageSize]);

  const { data: logsData, loading, error: logsError } =
    useApi<{ logs: AuditLog[]; total: number }>(`/audit/logs?${logsQuery}`);
  const logs = logsError ? [] : (logsData?.logs ?? []);
  const total = logsError ? 0 : (logsData?.total ?? 0);

  const hasActiveFilters = !!(search || resourceType || actorId || dateFrom || dateTo);

  const columns: Column[] = [
    { id: "created_at", header: "Hora", className: "w-28" },
    { id: "actor", header: "Actor", className: "w-36" },
    { id: "action", header: "Acción" },
    { id: "resource_type", header: "Recurso", className: "w-32", hideBelow: "md" },
    { id: "ip", header: "IP", className: "w-28", hideBelow: "sm" },
    { id: "detail", header: "Detalle", className: "w-20 text-right", sticky: true },
  ];

  if (loading) return <Loading title="Auditoría" />;

  return (
    <>
      {/* Toolbar fila 1: búsqueda + exportar */}
      <div className="px-4 py-3 border-b border-border flex items-center gap-2">
        <div className="relative flex-1 min-w-0">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
          <Input
            className="h-8 pl-8 pr-3 bg-muted border-none text-13"
            placeholder="Filtrar por acción..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          />
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm" className="gap-1.5 text-muted-foreground" disabled={logs.length === 0}>
                <Download className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">Exportar</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {(["xlsx", "pdf"] as const).map((fmt) => (
                <DropdownMenuItem key={fmt} onClick={async () => {
                  const params = new URLSearchParams({ format: fmt });
                  if (search.trim()) params.set("action", search.trim());
                  if (resourceType) params.set("resource_type", resourceType);
                  if (actorId) params.set("actor_id", actorId);
                  if (dateFrom) params.set("date_from", new Date(dateFrom).toISOString());
                  if (dateTo) params.set("date_to", new Date(dateTo + "T23:59:59").toISOString());
                  const resp = await api.get(`/audit/logs/export?${params}`, { responseType: "blob" });
                  const url = URL.createObjectURL(resp.data as Blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `auditoria-${new Date().toISOString().slice(0, 10)}.${fmt}`;
                  a.click();
                  URL.revokeObjectURL(url);
                }}>
                  {fmt === "xlsx" ? "Excel (.xlsx)" : "PDF"}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Toolbar fila 2: filtros secundarios */}
      <div className="px-4 py-2 border-b border-border bg-muted/20 flex flex-col sm:flex-row sm:items-center gap-2 text-2xs">
        <div className="grid grid-cols-2 sm:flex gap-2">
          <select
            value={resourceType}
            onChange={(e) => { setResourceType(e.target.value); setPage(1); }}
            className="h-7 px-2 text-[12px] border border-border rounded-lg bg-card text-foreground focus:outline-none focus:ring-2 focus:ring-ring/50 min-w-0"
          >
            {RESOURCE_TYPES.map((rt) => (
              <option key={rt.value} value={rt.value}>{rt.label}</option>
            ))}
          </select>
          <select
            value={actorId}
            onChange={(e) => { setActorId(e.target.value); setPage(1); }}
            className="h-7 px-2 text-[12px] border border-border rounded-lg bg-card text-foreground focus:outline-none focus:ring-2 focus:ring-ring/50 min-w-0"
            title="Filtrar por actor"
          >
            <option value="">Todos los actores</option>
            {actors.map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
        </div>
        <DateRangeFilter
          size="sm"
          from={dateFrom}
          to={dateTo}
          onFromChange={(v) => { setDateFrom(v); setPage(1); }}
          onToChange={(v) => { setDateTo(v); setPage(1); }}
        />
        {hasActiveFilters && (
          <Button
            variant="link"
            onClick={() => {
              setSearch(""); setResourceType(""); setActorId("");
              setDateFrom(""); setDateTo(""); setPage(1);
            }}
            className="text-2xs h-auto p-0 sm:ml-auto"
          >
            Limpiar filtros
          </Button>
        )}
      </div>

      <DataTable<AuditLog>
        columns={columns}
        data={logs}
        rowKey={(e) => e.id}
        loading={false}
        empty={
          <EmptyState
            icon={ShieldCheck}
            title="Sin entradas"
            description="No hay acciones registradas con los filtros actuales."
            className="py-12"
          />
        }
        pagination={{
          total,
          page,
          pageSize,
          onPageChange: setPage,
          onPageSizeChange: (n) => { setPageSize(n); setPage(1); },
          itemLabel: "entradas",
        }}
      >
        {logs.map((entry) => {
          const actor = entry.actor_name ?? "sistema";
          const isSystem = !entry.actor_name;
          const hasDetail = !!entry.resource_id || !!entry.user_agent ||
            (entry.meta_json && Object.keys(entry.meta_json).length > 0);

          return (
            <tr key={entry.id} className="group border-b border-border/60 transition-colors hover:bg-muted/40">
              <td className="px-3 py-2 align-top">
                <span className="text-[12px] font-mono text-muted-foreground tabular-nums whitespace-nowrap">
                  {relativeTime(entry.created_at)}
                </span>
              </td>
              <td className="px-3 py-2 align-top">
                <div className="flex items-center gap-2">
                  <div
                    className={`w-6 h-6 rounded-full flex items-center justify-center text-3xs font-bold shrink-0 ${
                      isSystem ? "bg-muted text-muted-foreground" : actorColor(actor)
                    }`}
                  >
                    {isSystem ? "S" : actorInitials(actor)}
                  </div>
                  <span className="text-13 font-semibold text-foreground truncate">
                    {isSystem ? "sistema" : actor.split(" ")[0] + (actor.split(" ")[1] ? ` ${actor.split(" ")[1][0]}.` : "")}
                  </span>
                </div>
              </td>
              <td className="px-3 py-2 align-top">
                <p className="text-13 text-muted-foreground leading-snug">{entry.action}</p>
              </td>
              <td className="px-3 py-2 align-top hidden md:table-cell">
                <span className="text-2xs text-muted-foreground">{entry.resource_type ?? "—"}</span>
              </td>
              <td className="px-3 py-2 align-top hidden sm:table-cell">
                <span className="text-2xs font-mono text-muted-foreground/70">{entry.ip ?? "—"}</span>
              </td>
              <td className="px-3 py-2 align-top text-right sticky right-0 z-10 bg-card group-hover:bg-muted/40 border-l border-border/60">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-muted-foreground"
                  disabled={!hasDetail}
                  onClick={() => setDetail(entry)}
                >
                  <Eye className="w-3.5 h-3.5" />
                  <span className="hidden sm:inline ml-1">Ver</span>
                </Button>
              </td>
            </tr>
          );
        })}
      </DataTable>

      <Modal
        open={!!detail}
        onClose={() => setDetail(null)}
        title="Detalle de la entrada"
        subtitle={detail ? formatInProjectTz(detail.created_at) : undefined}
        size="lg"
      >
        {detail && (
          <div className="text-13 space-y-3">
            <div className="flex items-center gap-2">
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-3xs font-bold shrink-0 ${
                  !detail.actor_name ? "bg-muted text-muted-foreground" : actorColor(detail.actor_name ?? "sistema")
                }`}
              >
                {!detail.actor_name ? "S" : actorInitials(detail.actor_name ?? "sistema")}
              </div>
              <div className="min-w-0">
                <p className="font-semibold text-foreground truncate">{detail.actor_name ?? "sistema"}</p>
                <p className="text-2xs text-muted-foreground">{detail.action}</p>
              </div>
            </div>

            <dl className="grid grid-cols-[140px_1fr] gap-x-3 gap-y-2 text-2xs">
              <dt className="text-muted-foreground">Recurso</dt>
              <dd className="text-foreground break-all">{detail.resource_type ?? "—"}</dd>
              <dt className="text-muted-foreground">Resource ID</dt>
              <dd className="text-foreground break-all font-mono">{detail.resource_id ?? "—"}</dd>
              <dt className="text-muted-foreground">IP</dt>
              <dd className="text-foreground break-all font-mono">{detail.ip ?? "—"}</dd>
              <dt className="text-muted-foreground">User agent</dt>
              <dd className="text-foreground break-all">{detail.user_agent ?? "—"}</dd>
            </dl>

            {detail.meta_json && Object.keys(detail.meta_json).length > 0 && (
              <div>
                <p className="text-2xs text-muted-foreground mb-1.5">meta_json</p>
                <pre className="text-3xs text-foreground bg-muted/40 border border-border rounded-lg p-3 overflow-auto max-h-72">
{JSON.stringify(detail.meta_json, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </Modal>
    </>
  );
}
