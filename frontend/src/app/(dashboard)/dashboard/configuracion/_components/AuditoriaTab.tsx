"use client";

import { Fragment, useMemo, useState } from "react";
import { Search, ShieldCheck, Download, ArrowUp, ArrowDown, ArrowUpDown, ChevronDown, ChevronRight } from "lucide-react";
import api from "@/lib/api";
import { useApi } from "@/hooks/use-api";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from "@/components/ui/dropdown-menu";
import type { AuditLog } from "@/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState } from "@/components/ui/empty-state";
import { DateRangeFilter } from "@/components/composed/date-range-filter";
import { TablePagination } from "@/components/composed/table-pagination";
import { Loading } from "@/components/ui/loading";
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

type SortBy = "created_at" | "action" | "resource_type" | "actor_id" | "ip";
type SortDir = "asc" | "desc";

interface ActorOption { id: string; name: string; }

export function AuditoriaTab() {
  const [search, setSearch] = useState("");
  const [resourceType, setResourceType] = useState("");
  const [actorId, setActorId] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [sortBy, setSortBy] = useState<SortBy>("created_at");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Lista de actores: se carga una sola vez
  const { data: actorsData } = useApi<ActorOption[]>("/audit/actors");
  const actors = actorsData ?? [];

  const logsQuery = useMemo(() => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
      sort_by: sortBy,
      sort_dir: sortDir,
    });
    if (search.trim()) params.set("action", search.trim());
    if (resourceType) params.set("resource_type", resourceType);
    if (actorId) params.set("actor_id", actorId);
    if (dateFrom) params.set("date_from", new Date(dateFrom).toISOString());
    if (dateTo) params.set("date_to", new Date(dateTo + "T23:59:59").toISOString());
    return params.toString();
  }, [search, resourceType, actorId, dateFrom, dateTo, sortBy, sortDir, page, pageSize]);

  const { data: logsData, loading, error: logsError } =
    useApi<{ logs: AuditLog[]; total: number }>(`/audit/logs?${logsQuery}`);
  const logs = logsError ? [] : (logsData?.logs ?? []);
  const total = logsError ? 0 : (logsData?.total ?? 0);

  function toggleSort(field: SortBy) {
    if (sortBy === field) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortBy(field);
      setSortDir("desc");
    }
    setPage(1);
  }

  function SortIcon({ field }: { field: SortBy }) {
    if (sortBy !== field) return <ArrowUpDown className="w-3.5 h-3.5 opacity-40" />;
    return sortDir === "asc" ? <ArrowUp className="w-3.5 h-3.5" /> : <ArrowDown className="w-3.5 h-3.5" />;
  }

  const hasActiveFilters = !!(search || resourceType || actorId || dateFrom || dateTo);

  return (
    <>
      {loading ? (
        <Loading title="Auditoría" />
      ) : (
      <Card className="overflow-hidden">
      {/* Toolbar fila 1: búsqueda + acciones siempre en la misma línea —
          la búsqueda se encoge (flex-1 min-w-0), los botones quedan fijos
          al lado opuesto sin romper a una fila nueva. */}
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

      {/* Toolbar fila 2: todos los filtros secundarios (recurso, actor, IP,
          fechas) agrupados juntos, separados de las acciones de la fila 1. */}
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

      {logs.length === 0 ? (
          <EmptyState
            icon={ShieldCheck}
            title="Sin entradas"
            description="No hay acciones registradas con los filtros actuales."
            className="py-12"
          />
      ) : (
        <>
        <div className="overflow-x-auto"><Table className="min-w-190">
          <TableHeader>
            <TableRow>
              <TableHead className="w-8" />
              <TableHead
                className="w-32 cursor-pointer select-none hover:text-foreground"
                onClick={() => toggleSort("created_at")}
              >
                <span className="inline-flex items-center gap-1">Hora <SortIcon field="created_at" /></span>
              </TableHead>
              <TableHead
                className="w-36 cursor-pointer select-none hover:text-foreground"
                onClick={() => toggleSort("actor_id")}
              >
                <span className="inline-flex items-center gap-1">Actor <SortIcon field="actor_id" /></span>
              </TableHead>
              <TableHead
                className="cursor-pointer select-none hover:text-foreground"
                onClick={() => toggleSort("action")}
              >
                <span className="inline-flex items-center gap-1">Acción <SortIcon field="action" /></span>
              </TableHead>
              <TableHead
                className="w-32 hidden md:table-cell cursor-pointer select-none hover:text-foreground"
                onClick={() => toggleSort("resource_type")}
              >
                <span className="inline-flex items-center gap-1">Recurso <SortIcon field="resource_type" /></span>
              </TableHead>
              <TableHead
                className="w-28 hidden sm:table-cell cursor-pointer select-none hover:text-foreground"
                onClick={() => toggleSort("ip")}
              >
                <span className="inline-flex items-center gap-1">IP <SortIcon field="ip" /></span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {logs.map((entry) => {
              const actor = entry.actor_name ?? "sistema";
              const isSystem = !entry.actor_name;
              const isExpanded = expandedId === entry.id;
              const hasMeta = entry.meta_json && Object.keys(entry.meta_json).length > 0;

              return (
                <Fragment key={entry.id}>
                  <TableRow
                    className="cursor-pointer"
                    onClick={() => setExpandedId(isExpanded ? null : entry.id)}
                  >
                    <TableCell className="align-top">
                      {(hasMeta || entry.resource_id) ? (
                        isExpanded
                          ? <ChevronDown className="w-3.5 h-3.5 text-muted-foreground" />
                          : <ChevronRight className="w-3.5 h-3.5 text-muted-foreground" />
                      ) : null}
                    </TableCell>
                    <TableCell className="align-top">
                      <span className="text-[12px] font-mono text-muted-foreground tabular-nums whitespace-nowrap">
                        {relativeTime(entry.created_at)}
                      </span>
                    </TableCell>
                    <TableCell className="align-top">
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
                    </TableCell>
                    <TableCell className="align-top">
                      <p className="text-13 text-muted-foreground leading-snug">{entry.action}</p>
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      <span className="text-2xs text-muted-foreground">
                        {entry.resource_type ?? "—"}
                      </span>
                    </TableCell>
                    <TableCell className="hidden sm:table-cell">
                      <span className="text-2xs font-mono text-muted-foreground/70">
                        {entry.ip ?? "—"}
                      </span>
                    </TableCell>
                  </TableRow>
                  {isExpanded && (
                    <TableRow className="bg-muted/20 hover:bg-muted/20">
                      <TableCell colSpan={6}>
                        <div className="text-2xs space-y-1.5 font-mono">
                          {entry.resource_id && (
                            <div className="flex gap-2">
                              <span className="text-muted-foreground w-24">resource_id:</span>
                              <span className="text-foreground break-all">{entry.resource_id}</span>
                            </div>
                          )}
                          {entry.user_agent && (
                            <div className="flex gap-2">
                              <span className="text-muted-foreground w-24">user_agent:</span>
                              <span className="text-foreground break-all">{entry.user_agent}</span>
                            </div>
                          )}
                          {hasMeta && (
                            <div className="flex gap-2">
                              <span className="text-muted-foreground w-24">meta_json:</span>
                              <pre className="text-foreground bg-background border border-border rounded p-2 text-3xs overflow-auto max-h-60 flex-1">
{JSON.stringify(entry.meta_json, null, 2)}
                              </pre>
                            </div>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              );
            })}
          </TableBody>
         </Table></div>

          <TablePagination
            total={total}
            page={page}
            pageSize={pageSize}
            onPageChange={setPage}
            onPageSizeChange={(n) => { setPageSize(n); setPage(1); }}
            itemLabel="entradas"
          />
        </>
      )}
    </Card>
    )}
    </>
  );
}
