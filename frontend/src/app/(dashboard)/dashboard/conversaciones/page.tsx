"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import {
 MessageSquare, Search, ThumbsUp, ThumbsDown, Download,
 FileText, Zap, Database, Route, ChevronDown,
} from "lucide-react";
import api from "@/lib/api";
import { useApi, getErrorMessage } from "@/hooks/use-api";
import { timeAgo } from "@/lib/utils";
import type {
  ChatConversationDetail, ChatConversationOut, ChatMessageOut, ConversationStatus, MessageFeedback,
} from "@/types";

import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { DateRangeFilter } from "@/components/composed/date-range-filter";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from "@/components/ui/dropdown-menu";
import { useToast } from "@/components/ui/toast";
import { ConversacionesTabs } from "./_components/ConversacionesTabs";
import { PageHeader } from "@/components/ui/page-header";
import { TablePagination } from "@/components/composed/table-pagination";

function MessageFeedbackBar({ messageId, currentFeedback }: { messageId: string; currentFeedback: MessageFeedback | null }) {
 const [fb, setFb] = useState<MessageFeedback | null>(currentFeedback);

 async function handleFeedback(type: MessageFeedback) {
  if (fb === type) return;
  setFb(type);
  try { await api.patch(`/conversations/messages/${messageId}/feedback`, { feedback: type }); } catch { /* ignore */ }
 }

 return (
  <div className="flex items-center gap-0.5 mt-1.5" role="group" aria-label="Retroalimentación de la respuesta">
   <Button
    type="button"
    variant="ghost"
    size="icon"
    onClick={() => handleFeedback("positive")}
    aria-label="Marcar como útil"
    aria-pressed={fb === "positive"}
    title="Útil"
    className={`h-6 w-6 ${fb === "positive" ? "text-success bg-success/10 hover:bg-success/15" : "text-muted-foreground/40 hover:text-muted-foreground"}`}
   >
    <ThumbsUp className="h-3 w-3" aria-hidden="true" />
   </Button>
   <Button
    type="button"
    variant="ghost"
    size="icon"
    onClick={() => handleFeedback("negative")}
    aria-label="Marcar como no útil"
    aria-pressed={fb === "negative"}
    title="No útil"
    className={`h-6 w-6 ${fb === "negative" ? "text-destructive bg-destructive/10 hover:bg-destructive/15" : "text-muted-foreground/40 hover:text-muted-foreground"}`}
   >
    <ThumbsDown className="h-3 w-3" aria-hidden="true" />
   </Button>
  </div>
 );
}

function RouteBadge({ route }: { route: string | null }) {
 if (!route) return null;
 const meta: Record<string, { label: string; cls: string; Icon: typeof Zap }> = {
  cache: { label: "Caché", cls: "bg-brand-teal/10 text-brand-teal border-brand-teal/20", Icon: Zap },
  direct: { label: "Directo", cls: "bg-info/10 text-info border-info/20", Icon: Route },
  retrieval: { label: "RAG", cls: "bg-success/10 text-success border-success/20", Icon: Database },
  corrective_rag: { label: "Corrective RAG", cls: "text-warning border-warning/30", Icon: Database },
  no_context: { label: "Sin contexto", cls: "bg-muted text-muted-foreground border-border", Icon: Route },
 };
 const m = meta[route] ?? { label: route, cls: "bg-muted text-muted-foreground border-border", Icon: Route };
 const I = m.Icon;
 return (
  <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-3xs font-medium ${m.cls}`}>
   <I className="h-3 w-3" aria-hidden="true" />
   {m.label}
  </span>
 );
}

function SourcesDisclosure({ sources }: { sources: ChatMessageOut["sources_json"] }) {
 const [open, setOpen] = useState(false);
 if (!sources || sources.length === 0) return null;
 return (
  <div className="mt-1.5">
   <button
    type="button"
    onClick={() => setOpen((v) => !v)}
    aria-expanded={open}
    aria-label={open ? "Ocultar fuentes" : `Mostrar ${sources.length} fuentes`}
    className="inline-flex items-center gap-1 py-1 -my-1 text-3xs text-muted-foreground hover:text-foreground transition rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
   >
    <FileText className="h-3 w-3" aria-hidden="true" />
    <span>{sources.length} {sources.length === 1 ? "fuente" : "fuentes"}</span>
    <ChevronDown className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
   </button>
   {open && (
    <ul className="mt-1 space-y-1">
      {sources.map((s) => (
       <li key={s.source_name} className="text-3xs text-muted-foreground border-l-2 border-border pl-2 py-0.5">
       <div className="flex items-center justify-between gap-2">
        <span className="truncate font-medium text-foreground/80">{s.source_name}</span>
        <span className="tabular-nums shrink-0">{(s.score * 100).toFixed(0)}%</span>
       </div>
       {s.content && <p className="mt-0.5 line-clamp-2 leading-snug">{s.content}</p>}
      </li>
     ))}
    </ul>
   )}
  </div>
 );
}

type StatusFilter = ConversationStatus | "all";
// Sin chip "Escaladas": esas conversaciones ya tienen su propia pestaña de
// ruta (/conversaciones/escalamientos) — repetir el filtro aquí duplicaba
// la misma distinción con dos mecanismos distintos (ruta vs. query param).
const STATUS_CHIPS: { value: StatusFilter; label: string }[] = [
 { value: "all", label: "Todas" },
 { value: "active", label: "Activas" },
 { value: "resolved", label: "Resueltas" },
];

function statusBadgeVariant(s: ConversationStatus): "success" | "destructive" | "secondary" {
 if (s === "active") return "success";
 if (s === "escalated") return "destructive";
 return "secondary";
}

export default function HistorialPage() {
 const searchParams = useSearchParams();
 const { toast } = useToast();
 const [page, setPage] = useState(1);
 const [selected, setSelected] = useState<string | null>(() => searchParams.get("id"));
 const [detail, setDetail] = useState<ChatConversationDetail | null>(null);

 useEffect(() => {
  setSelected(searchParams.get("id"));
 }, [searchParams]);
 const [search, setSearch] = useState("");
 const [dateFrom, setDateFrom] = useState("");
 const [dateTo, setDateTo] = useState("");
 const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
 const [exporting, setExporting] = useState(false);
 const [pageSize, setPageSize] = useState(20);

 const listQuery = useMemo(() => {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize), source: "production" });
  if (search.trim()) params.set("search", search.trim());
  if (dateFrom) params.set("date_from", new Date(dateFrom).toISOString());
  if (dateTo) params.set("date_to", new Date(dateTo + "T23:59:59").toISOString());
  if (statusFilter !== "all") params.set("status", statusFilter);
  return params.toString();
 }, [page, pageSize, search, dateFrom, dateTo, statusFilter]);

 const { data: listData, loading, error: listError } =
  useApi<{ items: ChatConversationOut[]; total: number }>(`/conversations?${listQuery}`);
 const conversations = listData?.items ?? [];
 const total = listData?.total ?? 0;

 useEffect(() => {
  if (listError) toast({ type: "error", message: "No se pudo cargar el historial de conversaciones." });
 }, [listError, toast]);

 useEffect(() => {
  if (!selected) { setDetail(null); return; }
  const controller = new AbortController();
  api.get<ChatConversationDetail>(`/conversations/${selected}`, { signal: controller.signal })
   .then(({ data }) => setDetail(data))
   .catch((err) => { if (!controller.signal.aborted) console.error(err); });
  return () => controller.abort();
 }, [selected]);

 async function handleExport(format: string) {
  if (exporting) return;
  setExporting(true);
  const params = new URLSearchParams({ format, source: "production" });
  if (search.trim()) params.set("search", search.trim());
  if (dateFrom) params.set("date_from", new Date(dateFrom).toISOString());
  if (dateTo) params.set("date_to", new Date(dateTo + "T23:59:59").toISOString());
  if (statusFilter !== "all") params.set("status", statusFilter);
  try {
   const res = await api.get(`/conversations/export?${params}`, { responseType: "blob" });
   const url = URL.createObjectURL(res.data as Blob);
   const a = document.createElement("a");
   const cd = (res.headers["content-disposition"] as string | undefined) ?? "";
   const match = cd.match(/filename="?([^"]+)"?/);
   a.href = url;
   a.download = match?.[1] ?? `conversaciones-${new Date().toISOString().slice(0, 10)}.${format}`;
   a.click();
   URL.revokeObjectURL(url);
  } catch (err) {
   toast({ type: "error", message: getErrorMessage(err, "No se pudo exportar las conversaciones.") });
  } finally {
   setExporting(false);
  }
 }

 return (
  <div>
   <PageHeader
    icon={MessageSquare}
    title="Conversaciones"
    tip="Historial del chatbot, preguntas sin responder y chats escalados."
   />
   <ConversacionesTabs />

   {/* Responsive: stack on mobile, split panel de altura fija desde lg (como Gmail/Slack).
       dvh en vez de vh: en móviles evita que la barra de navegador oculte contenido. */}
   <div className="flex flex-col lg:flex-row gap-4 lg:h-[calc(100dvh-19rem)] lg:min-h-100">
    {/* Conversation list */}
    <Card className="w-full lg:max-w-sm lg:shrink-0 overflow-hidden flex flex-col">
     <div className="p-3 border-b space-y-2">
      <div className="flex items-center justify-between gap-2">
       <span className="text-2xs text-muted-foreground tabular-nums">{total} conversaciones</span>
       <DropdownMenu>
        <DropdownMenuTrigger asChild>
         <Button variant="outline" size="sm" className="gap-1.5" disabled={exporting}>
          <Download className="h-3.5 w-3.5" aria-hidden="true" /> {exporting ? "Exportando..." : "Exportar"}
         </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent>
         <DropdownMenuItem onClick={() => handleExport("xlsx")}>Excel (.xlsx)</DropdownMenuItem>
         <DropdownMenuItem onClick={() => handleExport("pdf")}>PDF</DropdownMenuItem>
        </DropdownMenuContent>
       </DropdownMenu>
      </div>
      <div className="relative">
       <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" aria-hidden="true" />
       <Input
        className="pl-8 h-8"
        placeholder="Buscar en mensajes..."
        aria-label="Buscar en mensajes"
        value={search}
        onChange={(e) => { setSearch(e.target.value); setPage(1); }}
       />
      </div>
      <DateRangeFilter
       size="sm"
       from={dateFrom}
       to={dateTo}
       onFromChange={(v) => { setDateFrom(v); setPage(1); }}
       onToChange={(v) => { setDateTo(v); setPage(1); }}
      />
      {/* Status chips */}
      <div className="flex flex-wrap items-center gap-1.5" role="tablist" aria-label="Filtrar por estado">
       {STATUS_CHIPS.map((chip) => {
        const active = statusFilter === chip.value;
        return (
         <Button
          key={chip.value}
          type="button"
          role="tab"
          aria-selected={active}
          variant={active ? "default" : "outline"}
          size="xs"
          onClick={() => { setStatusFilter(chip.value); setPage(1); }}
          className="h-6 px-2.5 text-2xs rounded-full"
         >
          {chip.label}
         </Button>
        );
       })}
      </div>
     </div>

     <div className="flex-1 overflow-y-auto divide-y max-h-[60vh] lg:max-h-none min-h-0">
      {loading ? (
       <div className="p-4 space-y-3">{[1,2,3,4,5].map(i => <Skeleton key={i} className="h-14 w-full" />)}</div>
      ) : conversations.length === 0 ? (
       <EmptyState
        icon={MessageSquare}
        title="Aún no hay conversaciones"
        description="Cuando alguien interactúe con el chatbot las verá aquí. Pruebe el bot usted mismo para confirmar que funciona."
        action={
         <Link href="/dashboard/configuracion/playground">
          <Button size="sm" className="gap-1.5">
           <MessageSquare className="w-3.5 h-3.5" /> Probar el bot
          </Button>
         </Link>
        }
        className="py-12"
       />
      ) : (
       conversations.map((c) => (
        <button
         key={c.id}
         type="button"
         onClick={() => setSelected(c.id === selected ? null : c.id)}
         aria-pressed={selected === c.id}
         className={`w-full text-left px-4 py-3 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/50 ${selected === c.id ? "bg-primary/5" : "hover:bg-muted/50"}`}
        >
         <div className="flex items-center justify-between gap-2 mb-1">
          <span className="truncate text-13 text-foreground">
           {c.first_user_message || <em className="text-muted-foreground">(sin mensajes)</em>}
          </span>
          <Badge variant={statusBadgeVariant(c.status)} className="text-3xs shrink-0">
           {c.status}
          </Badge>
         </div>
<div className="flex items-center gap-2 text-2xs text-muted-foreground min-w-0">
           <span className="shrink-0">{timeAgo(c.last_message_at)}</span>
          <span aria-hidden="true" className="shrink-0">·</span>
          <span className="shrink-0">{c.message_count} msgs</span>
          {c.device && <><span aria-hidden="true" className="shrink-0">·</span><span className="truncate min-w-0">{c.device}</span></>}
         </div>
        </button>
       ))
      )}
     </div>

     <TablePagination
      total={total}
      page={page}
      pageSize={pageSize}
      onPageChange={setPage}
      onPageSizeChange={(n) => { setPageSize(n); setPage(1); }}
      itemLabel="conversaciones"
     />
    </Card>

    {/* Detail panel */}
    <Card className="flex-1 overflow-hidden flex flex-col min-h-100">
     {detail ? (
      <>
       <div className="px-6 py-3 border-b bg-muted/30">
        <div className="flex items-center justify-between gap-2 mb-1">
         <Badge variant={statusBadgeVariant(detail.status)} className="text-3xs">{detail.status}</Badge>
         <p className="text-2xs font-mono text-muted-foreground truncate">{detail.session_id}</p>
        </div>
<p className="text-2xs text-muted-foreground">
          {timeAgo(detail.last_message_at)} · {detail.device ?? "Desconocido"} · {detail.message_count} mensajes
         </p>
       </div>
       <div className="flex-1 min-h-0 p-4 sm:p-6 space-y-4 overflow-y-auto">
        {detail.messages.map((msg) => (
         <div key={msg.id} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
          <div className="max-w-[80%] sm:max-w-[75%]">
           <div
            className={`px-3.5 py-2.5 rounded-xl text-13 leading-relaxed whitespace-pre-wrap wrap-break-word ${
             msg.role === "user" ? "bg-primary text-primary-foreground rounded-br-sm" : "bg-muted rounded-bl-sm"
            }`}
           >
            {msg.content}
           </div>
           {msg.role === "assistant" && (
            <>
             <div className="flex items-center gap-1.5 mt-1 flex-wrap">
              <RouteBadge route={msg.rag_route} />
              {msg.latency_ms != null && (
               <span className="text-3xs text-muted-foreground tabular-nums">{msg.latency_ms}ms</span>
              )}
             </div>
             <SourcesDisclosure sources={msg.sources_json} />
             <MessageFeedbackBar messageId={msg.id} currentFeedback={msg.feedback} />
            </>
           )}
          </div>
         </div>
        ))}
       </div>
      </>
     ) : (
      <div className="flex-1 flex flex-col items-center justify-center p-8">
       <EmptyState icon={MessageSquare} title="Seleccione una conversación" description="Los mensajes aparecerán aquí" />
      </div>
     )}
    </Card>
   </div>
  </div>
 );
}
