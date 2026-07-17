"use client";

import { useState } from "react";
import {
  FileSpreadsheet, MessageSquare, TrendingUp,
  Bell, BookOpen, Download, Loader2, CheckCircle2,
} from "lucide-react";
import api from "@/lib/api";
import { getErrorMessage } from "@/hooks/use-api";
import { isoDay } from "@/lib/utils";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { DateRangeFilter } from "@/components/composed/date-range-filter";

type ReportType = "ejecutivo" | "uso" | "escalamientos" | "conocimiento";

interface ReportCard {
  type: ReportType;
  title: string;
  description: string;
  includes: string[];
  icon: typeof MessageSquare;
  accent: string;
}

const REPORTS: ReportCard[] = [
  {
    type: "ejecutivo",
    title: "Reporte Ejecutivo",
    description: "Indicadores clave del período seleccionado, con comparativa frente al período anterior.",
    includes: [
      "Resumen del período con hallazgos clave",
      "Comparativa con el período anterior",
      "Gráficas de tendencia, temas y satisfacción",
      "Contención y motivos de escalamiento",
      "Preguntas sin responder",
    ],
    icon: TrendingUp,
    accent: "text-primary bg-primary/10",
  },
  {
    type: "uso",
    title: "Uso y Temas",
    description: "Detalle de la actividad del período: volumen, temas y canales.",
    includes: [
      "Tendencia diaria de consultas con gráfica",
      "Listado completo de temas con resolución",
      "Tendencia diaria de reacciones",
      "Distribución por dispositivo y canal con gráficas",
    ],
    icon: MessageSquare,
    accent: "text-brand-teal bg-brand-teal/10",
  },
  {
    type: "escalamientos",
    title: "Escalamientos",
    description: "Conversaciones que requirieron atención humana en el período.",
    includes: [
      "Contención, resolución y tiempos promedio",
      "Satisfacción promedio de 1 a 5",
      "Desglose por estado con gráfica",
      "Motivos de escalamiento con gráfica",
    ],
    icon: Bell,
    accent: "text-warning bg-warning/10",
  },
  {
    type: "conocimiento",
    title: "Base de Conocimiento",
    description: "Estado del contenido cargado y su aprovechamiento en el período.",
    includes: [
      "Fuentes y fragmentos por estado de revisión",
      "Fuentes más citadas en las respuestas",
      "Fuentes aprobadas sin uso en el período",
      "Preguntas sin responder por tema",
    ],
    icon: BookOpen,
    accent: "text-brand-steel bg-brand-steel/10",
  },
];

export default function ReportesPage() {
  const { toast } = useToast();
  const today = isoDay(new Date());
  const [dateFrom, setDateFrom] = useState(isoDay(new Date(Date.now() - 29 * 86400000)));
  const [dateTo, setDateTo] = useState(today);
  const [loading, setLoading] = useState<Record<ReportType, boolean>>({
    ejecutivo: false, uso: false, escalamientos: false, conocimiento: false,
  });
  const [lastDownloaded, setLastDownloaded] = useState<Record<ReportType, string | null>>({
    ejecutivo: null, uso: null, escalamientos: null, conocimiento: null,
  });

  const rangeInvalid = !dateFrom || !dateTo || dateFrom > dateTo;

  async function handleGenerate(type: ReportType) {
    if (rangeInvalid) {
      toast({ type: "error", message: "Seleccione un rango de fechas válido." });
      return;
    }
    setLoading((prev) => ({ ...prev, [type]: true }));
    try {
      const resp = await api.post(
        `/analytics/reports?report_type=${type}&date_from=${dateFrom}&date_to=${dateTo}&source=production`,
        {},
        { responseType: "blob" },
      );
      const blob = resp.data as Blob;
      const contentType = (resp.headers["content-type"] as string | undefined) ?? "";
      if (contentType.includes("application/json")) {
        throw new Error("unexpected JSON response");
      }
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `reporte-${type}-${dateTo}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
      setLastDownloaded((prev) => ({
        ...prev,
        [type]: new Date().toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" }),
      }));
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo generar el reporte. Inténtelo de nuevo.") });
    } finally {
      setLoading((prev) => ({ ...prev, [type]: false }));
    }
  }

  return (
    <div>
      <PageHeader
        icon={FileSpreadsheet}
        title="Reportes"
        tip="Genere y descargue reportes en PDF del período que seleccione."
      />

      {/* Rango de fechas */}
      <div className="flex flex-wrap items-end gap-3 mb-6">
        <DateRangeFilter
          size="sm"
          showLabels
          from={dateFrom}
          to={dateTo}
          maxDate={today}
          onFromChange={setDateFrom}
          onToChange={setDateTo}
        />
        {rangeInvalid && (
          <p className="text-xs text-destructive pb-2.5">
            La fecha inicial debe ser anterior o igual a la final.
          </p>
        )}
      </div>

      {/* Tarjetas de reportes */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {REPORTS.map((report) => {
          const Icon = report.icon;
          const isLoading = loading[report.type];
          const downloaded = lastDownloaded[report.type];

          return (
            <Card key={report.type} className="flex flex-col">
              <CardHeader className="pb-3">
                <div className="flex items-start gap-3">
                  <div className={`p-2.5 rounded-lg shrink-0 ${report.accent}`}>
                    <Icon className="w-4 h-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <CardTitle className="text-15 font-semibold">{report.title}</CardTitle>
                    <CardDescription className="text-xs mt-0.5 leading-relaxed">
                      {report.description}
                    </CardDescription>
                  </div>
                </div>
              </CardHeader>

              <CardContent className="flex-1 flex flex-col gap-4">
                <ul className="space-y-1">
                  {report.includes.map((item) => (
                    <li key={item} className="flex items-center gap-2 text-2xs text-muted-foreground">
                      <span className="w-1 h-1 rounded-full bg-muted-foreground/50 shrink-0" />
                      {item}
                    </li>
                  ))}
                </ul>

                <div className="flex items-center justify-between gap-3 mt-auto pt-3 border-t border-border">
                  <div className="text-2xs text-muted-foreground">
                    {downloaded ? (
                      <span className="flex items-center gap-1 text-success">
                        <CheckCircle2 className="w-3 h-3" />
                        Descargado a las {downloaded}
                      </span>
                    ) : (
                      <span>Del {dateFrom} al {dateTo}</span>
                    )}
                  </div>

                  <Button
                    size="sm"
                    variant="outline"
                    className="gap-1.5 shrink-0"
                    disabled={isLoading || rangeInvalid}
                    onClick={() => handleGenerate(report.type)}
                  >
                    {isLoading ? (
                      <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Generando...</>
                    ) : (
                      <><Download className="w-3.5 h-3.5" /> Descargar PDF</>
                    )}
                  </Button>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
