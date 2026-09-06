"use client";

import { useRef, useState } from "react";
import { Search, Zap, FileText, Loader2, Check, X } from "lucide-react";
import api from "@/lib/api";
import type { Source } from "@/types";
import { useApi, getErrorMessage } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";

interface ChunkTestResult {
 text: string;
 source_name: string;
 score: number;
 chunk_index: number;
 section: string | null;
 relevant: boolean;
 truncated: boolean;
}

interface ChunkTestResponse {
 chunks: ChunkTestResult[];
 latency_ms: number;
 graded: boolean;
}

export default function ChunkTestPage() {
 const { toast } = useToast();
 const [query, setQuery] = useState("");
 const [topK, setTopK] = useState(5);
 const [sourceFilter, setSourceFilter] = useState<string[]>([]);
 const { data: sourcesData } = useApi<Source[]>("/sources");
 const sources = (sourcesData ?? []).filter((s) => s.status === "ready");
 const [results, setResults] = useState<ChunkTestResponse | null>(null);
 const [loading, setLoading] = useState(false);
 // Token de la request más reciente: evita que una respuesta vieja sobrescriba una más nueva.
 const latestRequestRef = useRef(0);

 async function handleTest() {
  if (!query.trim()) return;
  const requestId = ++latestRequestRef.current;
  setLoading(true);
  try {
   const { data } = await api.post<ChunkTestResponse>("/chunks/test-query", {
    query: query.trim(),
    source_ids: sourceFilter.length > 0 ? sourceFilter : null,
    top_k: topK,
   });
   if (requestId !== latestRequestRef.current) return; // superada por una consulta más nueva
   setResults(data);
  } catch (err) {
   if (requestId !== latestRequestRef.current) return;
   setResults(null);
   toast({ type: "error", message: getErrorMessage(err, "Error al ejecutar la consulta de prueba.") });
  } finally {
   if (requestId === latestRequestRef.current) setLoading(false);
  }
 }

 function handleKeyDown(e: React.KeyboardEvent) {
  if (e.key === "Enter") handleTest();
 }

 // El texto de cada fragmento empieza con "[Sección: ... | Parte x/y, Fragmento n/m]",
 // un encabezado que se añade al indexar. Separarlo evita mostrarlo como contenido.
 function splitPrefix(text: string): { prefix: string | null; body: string } {
  const m = text.match(/^\[([^\]]+)\]\s*/);
  return m ? { prefix: m[1], body: text.slice(m[0].length) } : { prefix: null, body: text };
 }

 return (
  <div>
   <PageHeader
    icon={Search}
    title="Búsqueda"
    tip="Pruebe qué fragmentos recupera el chatbot para una pregunta y cuáles usaría para responder, sin generar la respuesta."
   />

   <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
    {/* Panel de configuración */}
    <Card>
     <CardHeader>
      <CardTitle className="text-15">Configuración</CardTitle>
     </CardHeader>
     <CardContent className="space-y-5">
      <div className="space-y-2">
       <Label>Pregunta</Label>
       <div className="flex gap-2">
        <Input
         value={query}
         onChange={(e) => setQuery(e.target.value)}
         onKeyDown={handleKeyDown}
         placeholder="Ej: ¿Cuáles son los requisitos de matrícula?"
        />
        <Button onClick={handleTest} disabled={loading || !query.trim()} size="icon" aria-label="Buscar">
         {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Search className="h-4 w-4" aria-hidden="true" />}
        </Button>
       </div>
      </div>

      <div className="space-y-2">
       <Label>Fragmentos a recuperar: {topK}</Label>
       <Slider value={topK} onValueChange={setTopK} min={1} max={20} step={1} />
      </div>

      {sources.length > 0 && (
       <div className="space-y-2">
        <Label>Filtrar por fuente</Label>
        <div className="flex flex-wrap gap-1.5">
         {sources.map((s) => {
          const active = sourceFilter.includes(s.id);
          return (
           <button
            key={s.id}
            onClick={() =>
             setSourceFilter((prev) =>
              active ? prev.filter((id) => id !== s.id) : [...prev, s.id]
             )
            }
            className={`h-7 px-3 text-xs font-medium rounded-full border transition ${
             active ? "bg-primary text-primary-foreground border-primary" : "bg-background text-muted-foreground border-border hover:bg-muted-foreground/10 hover:text-foreground"
            }`}
           >
            {s.name}
           </button>
          );
         })}
        </div>
        {sourceFilter.length > 0 && (
         <button onClick={() => setSourceFilter([])} className="text-2xs text-muted-foreground hover:text-foreground">
          Limpiar filtro
         </button>
        )}
       </div>
      )}
     </CardContent>
    </Card>

    {/* Panel de resultados */}
    <div className="lg:col-span-2 space-y-4">
     {results && (
      <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
       <Badge variant="secondary" className="gap-1 text-3xs">
        <Zap className="h-3 w-3" /> {results.latency_ms}ms
       </Badge>
       <span>
        {results.chunks.length} fragmentos recuperados
        {results.graded &&
         `, ${results.chunks.filter((c) => c.relevant).length} que el chatbot usaría`}
       </span>
      </div>
     )}

     {loading ? (
      <div className="space-y-3">
       {[1, 2, 3].map((i) => <Skeleton key={i} className="h-32 w-full" />)}
      </div>
     ) : !results ? (
      <Card>
       <CardContent>
        <EmptyState
         icon={Search}
         title="Escriba una pregunta para empezar"
         description="Los resultados de la busqueda vectorial aparecerán aquí con sus scores de relevancia"
        />
       </CardContent>
      </Card>
     ) : results.chunks.length === 0 ? (
      <Card>
       <CardContent>
        <EmptyState icon={FileText} title="Sin resultados" description="No hay fragmentos indexados que coincidan con esta consulta" />
       </CardContent>
      </Card>
     ) : (
      results.chunks.map((chunk, i) => {
       const { prefix, body } = splitPrefix(chunk.text);
       const descartado = results.graded && !chunk.relevant;
       return (
        <Card key={i} className={descartado ? "opacity-60" : undefined}>
         <CardContent className="p-4">
          <div className="flex flex-wrap items-center gap-2 mb-3">
           <Badge variant="outline" className="font-mono text-3xs">
            #{i + 1}
           </Badge>
           {results.graded && (
            <Badge
             variant={chunk.relevant ? "default" : "secondary"}
             className="text-3xs gap-1"
            >
             {chunk.relevant ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
             {chunk.relevant ? "El chatbot lo usa" : "Descartado"}
            </Badge>
           )}
           <span className="flex-1" />
           <Badge variant="secondary" className="text-3xs">
            <FileText className="h-3 w-3 mr-1" /> {chunk.source_name}
           </Badge>
           {chunk.section && (
            <Badge variant="outline" className="text-3xs">
             {chunk.section}
            </Badge>
           )}
          </div>
          {prefix && (
           <p className="text-2xs text-muted-foreground font-mono mb-1.5">{prefix}</p>
          )}
          <p className="text-13 leading-relaxed whitespace-pre-wrap">{body}</p>
          {chunk.truncated && (
           <p className="text-2xs text-muted-foreground mt-2 italic">
            Vista previa recortada; el fragmento completo es más largo.
           </p>
          )}
         </CardContent>
        </Card>
       );
      })
     )}
    </div>
   </div>
  </div>
 );
}
